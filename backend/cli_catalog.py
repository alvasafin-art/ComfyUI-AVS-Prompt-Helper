"""Provider-specific model discovery. Never sends a user/model turn."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import tomllib

from .codex_catalog import safe_diagnostic, failure_detail


def kimi_config():
    source = Path(os.environ.get('AVS_KIMI_CONFIG', str(Path.home() / '.kimi/config.toml'))).expanduser()
    try:
        raw = source.read_text(encoding='utf-8')
        configured = json.loads(raw) if source.suffix.lower() == '.json' else tomllib.loads(raw)
        if not isinstance(configured, dict):
            raise ValueError('Expected configuration object')
        return configured
    except (OSError, ValueError) as exc:
        raise ValueError('Kimi configuration missing or invalid. Run kimi login/setup on the server or set AVS_KIMI_CONFIG') from exc


def kimi_models(configured):
    models = []
    for alias, item in configured.get('models', {}).items():
        if not isinstance(item, dict) or item.get('provider') not in configured.get('providers', {}):
            continue
        ident = item.get('model')
        if not isinstance(ident, str) or not ident:
            continue
        caps = set(item.get('capabilities') or [])
        # Same derivation as kimi_cli.llm.derive_model_capabilities.
        if 'thinking' in ident.lower() or 'reason' in ident.lower():
            caps.update(('thinking', 'always_thinking'))
        elif ident in {'kimi-for-coding', 'kimi-code'}:
            caps.add('thinking')
        efforts = ['thinking'] if 'always_thinking' in caps else ['thinking', 'no_thinking'] if 'thinking' in caps else []
        models.append({'id': alias, 'name': item.get('display_name') or ident,
                       'reasoning': efforts, 'is_default': alias == configured.get('default_model')})
    return models


def claude_models(rows):
    models = []
    for item in rows:
        ident = item.get('value')
        if not isinstance(ident, str) or not ident:
            continue
        levels = item.get('supportedEffortLevels')
        efforts = [e for e in levels if e in {'low', 'medium', 'high', 'xhigh', 'max'}] if isinstance(levels, list) else None
        if item.get('supportsEffort') is False:
            efforts = []
        models.append({'id': ident, 'name': item.get('displayName') or ident, 'reasoning': efforts})
    return models


def discover_claude(executable, timeout=35):
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix='avs-claude-catalog-') as directory, tempfile.TemporaryFile() as errors:
        mcp = Path(directory) / 'mcp.json'
        mcp.write_text('{"mcpServers":{}}', encoding='utf-8')
        args = executable + ['--print', '--bare', '--tools', '', '--strict-mcp-config', '--mcp-config', str(mcp),
                             '--setting-sources', '', '--settings', '{"disableAllHooks":true}', '--no-session-persistence',
                             '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose']
        process = subprocess.Popen(args, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, shell=False)
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
        try:
            # Same handshake used by Claude Agent SDK supportedModels(). No prompt.
            message = {'type': 'control_request', 'request_id': 'avs-models',
                       'request': {'subtype': 'initialize', 'hooks': None}}
            process.stdin.write((json.dumps(message) + '\n').encode())
            process.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('Claude model discovery timed out; check CLI version and connectivity')
                try:
                    event = inbox.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ValueError('Claude model discovery timed out; check CLI version and connectivity') from exc
                if event is None:
                    errors.seek(0)
                    raise ValueError('Claude discovery stopped: ' + failure_detail(b'', errors.read()))
                response = event.get('response', {})
                if event.get('type') != 'control_response' or response.get('request_id') != 'avs-models':
                    continue
                if response.get('subtype') != 'success':
                    raise ValueError('Claude discovery: ' + safe_diagnostic(response.get('error', 'Initialization failed')))
                models = claude_models(response.get('response', {}).get('models', []))
                if not models:
                    raise ValueError('Claude CLI returned no model catalogue. Update Claude Code or enter the model manually')
                return {'models': models, 'source': 'claude initialize',
                        'message': f'Loaded {len(models)} models from Claude CLI. Inference/account access not tested.'}
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            worker.join(timeout=2)
            process.stdin.close()
            process.stdout.close()


def discover(provider):
    from .extra_cli import capabilities
    executable = capabilities(provider)
    if provider == 'claude':
        return discover_claude(executable)
    models = kimi_models(kimi_config())
    if not models:
        raise ValueError('No configured Kimi models. Run kimi login/setup and choose models with /model first')
    return {'models': models, 'source': 'kimi configuration',
            'message': f'Loaded {len(models)} configured Kimi models. Login and remote access not tested; refresh the CLI catalogue with /model.'}
