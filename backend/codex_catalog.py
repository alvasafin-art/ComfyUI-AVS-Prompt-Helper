"""Read-only Codex app-server discovery; never starts a model turn."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time


def safe_diagnostic(value, private=()):
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', str(value))
    secrets = list(private) + [v for k, v in os.environ.items() if any(t in k.upper() for t in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')) and len(v) >= 8]
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)(bearer\s+)\S+', r'\1[redacted]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', text)
    text = re.sub(r'(?i)((?:access_token|refresh_token|api_key|authorization|password)["\s:=]+)[^\s,}\"]+', r'\1[redacted]', text)
    text = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', text)
    return text.strip()[:1800]


def failure_detail(stdout, stderr, private=()):
    messages = []
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') in {'error', 'turn.failed'}:
            error = event.get('error', event)
            message = error.get('message') if isinstance(error, dict) else error
            if message:
                messages.append(str(message))
    if not messages:
        lines = stderr.decode('utf-8', errors='replace').splitlines()
        messages = [line for line in lines if re.search(r'(?i)error|invalid|unsupported|failed|unexpected|not found|denied', line)][-6:]
    return safe_diagnostic('\n'.join(dict.fromkeys(messages)) or 'CLI exited without a structured error.', private)


def normalize_models(rows):
    models = []
    for item in rows:
        ident = item.get('model') or item.get('id')
        if not isinstance(ident, str) or not ident:
            continue
        efforts = [e['reasoningEffort'] for e in item.get('supportedReasoningEfforts', [])
                   if isinstance(e, dict) and isinstance(e.get('reasoningEffort'), str)]
        models.append({'id': ident, 'name': item.get('displayName') or ident,
                       'reasoning': efforts, 'default_reasoning': item.get('defaultReasoningEffort'),
                       'is_default': bool(item.get('isDefault'))})
    return models


def discover(exe, timeout=35):
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix='avs-codex-catalog-') as directory, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([exe, 'app-server', '--listen', 'stdio://', '-c', 'model_provider="openai"'],
                                   cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, shell=False)
        inbox = queue.Queue()
        def reader():
            try:
                for line in process.stdout:
                    try:
                        inbox.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                inbox.put(None)
        worker = threading.Thread(target=reader, daemon=True)
        worker.start()
        sequence = 0
        def send(message):
            process.stdin.write((json.dumps(message)+'\n').encode())
            process.stdin.flush()
        def rpc(method, params):
            nonlocal sequence
            sequence += 1
            send({'id': sequence, 'method': method, 'params': params})
            while True:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise ValueError('Codex model discovery timed out; check server connectivity and login')
                try:
                    message = inbox.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ValueError('Codex model discovery timed out; check server connectivity and login') from exc
                if message is None:
                    errors.seek(0)
                    raise ValueError('Codex app-server stopped: '+failure_detail(b'', errors.read()))
                if message.get('id') != sequence:
                    continue
                if 'error' in message:
                    raise ValueError('Codex discovery: '+safe_diagnostic(message['error'].get('message', 'RPC error')))
                return message.get('result', {})
        try:
            rpc('initialize', {'clientInfo': {'name': 'avs_prompt_helper', 'title': 'AVS Prompt Helper', 'version': '0.3.0'}})
            send({'method': 'initialized', 'params': {}})
            account = rpc('account/read', {'refreshToken': False})
            if not account.get('account') and account.get('requiresOpenaiAuth', True):
                raise ValueError('Codex is not logged in for the ComfyUI server process. Run codex login with the same OS user and CODEX_HOME')
            rows, cursor = [], None
            for _ in range(10):
                page = rpc('model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
                rows.extend(page.get('data', []))
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            else:
                raise ValueError('Codex model catalogue exceeded pagination limit')
            models = normalize_models(rows)
            if not models:
                raise ValueError('Codex returned no available models for this account')
            auth_type = (account.get('account') or {}).get('type', 'provider')
            return {'message': f'Codex connected ({auth_type}). Loaded {len(models)} models. No generation requested.',
                    'models': models, 'source': 'codex model/list'}
        except (OSError, BrokenPipeError) as exc:
            raise ValueError('Codex app-server communication failed; check CLI version and server permissions') from exc
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            worker.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
