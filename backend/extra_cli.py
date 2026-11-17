"""Tool-free Claude Code and Kimi CLI transports. No shell command interpolation."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def command(provider):
    env_name = f"AVS_{provider.upper()}_EXECUTABLE"
    executable = shutil.which(os.environ.get(env_name, provider))
    if not executable:
        raise ValueError(f"{provider} CLI not found. Set {env_name} on the ComfyUI server")
    path = Path(executable)
    if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        if provider == "claude":
            script = path.parent / "node_modules/@anthropic-ai/claude-code/cli.js"
            node = shutil.which("node")
            if node and script.is_file():
                return [node, str(script)]
        raise ValueError(f"{env_name} must point to a native executable, not a shell script")
    return [executable]


def capabilities(provider):
    args = command(provider)
    result = subprocess.run(args + ["--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, shell=False)
    required = (["--print", "--bare", "--tools", "--strict-mcp-config", "--system-prompt-file", "--input-format", "--output-format", "--no-session-persistence"]
                if provider == "claude" else ["--print", "--agent-file", "--config-file", "--mcp-config-file", "--skills-dir", "--input-format", "--output-format", "--final-message-only"])
    if result.returncode or any(flag not in result.stdout for flag in required):
        raise ValueError(f"Update {provider} CLI: required noninteractive/isolation flags are unavailable")
    return args


def image_content(request, provider):
    content = [{"type": "text", "text": request.user}]
    for image in request.images:
        content.append({"type": "text", "text": f"Image @{image.label}:"})
        encoded = base64.b64encode(image.data).decode()
        if provider == "claude":
            content.append({"type": "image", "source": {"type": "base64", "media_type": image.mime, "data": encoded}})
        else:
            content.append({"type": "image_url", "image_url": {"url": f"data:{image.mime};base64,{encoded}", "id": image.label}})
    return content


def prepare(request, directory, executable):
    s = request.settings
    provider = s["adapter"]
    folder = Path(directory)
    mcp = folder / "mcp.json"
    mcp.write_text('{"mcpServers":{}}', encoding="utf-8")
    if provider == "claude":
        system = folder / "system.txt"
        system.write_text(request.system or "Return only the requested final text.", encoding="utf-8")
        args = executable + ["--print", "--bare", "--tools", "", "--strict-mcp-config", "--mcp-config", str(mcp),
                             "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                             "--no-session-persistence", "--model", s["model"], "--system-prompt-file", str(system),
                             "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--max-turns", "1"]
        if s["reasoning"] != "auto":
            if s["reasoning"] not in {"low", "medium", "high", "xhigh", "max"}:
                raise ValueError("Claude CLI reasoning supports Auto, low, medium, high, xhigh or max; model support varies")
            args += ["--effort", s["reasoning"]]
        message = {"type": "user", "message": {"role": "user", "content": image_content(request, provider)}}
    else:
        from .cli_catalog import kimi_config, kimi_models
        configured = kimi_config()
        if s["reasoning"] != "auto":
            model = next((m for m in kimi_models(configured) if m['id'] == s['model']), None)
            if not model or s['reasoning'] not in model['reasoning']:
                raise ValueError('Selected Kimi model does not support this thinking mode; test connection to refresh its capabilities')
        # Preserve authentication/provider definitions; exclude hooks, plugins and services.
        clean = {k: configured[k] for k in ("providers", "models", "default_model", "default_thinking") if k in configured}
        clean.update(loop_control={"max_steps_per_turn": 1, "max_retries_per_step": 1, "max_ralph_iterations": 0},
                     skip_afk_prompt_injection=True)
        config = folder / "config.json"
        with config.open("w", encoding="utf-8") as stream:
            os.chmod(config, 0o600)
            json.dump(clean, stream)
        # A fixed template prevents user-written Jinja/include syntax from being evaluated.
        (folder / "system.md").write_text("${AVS_SYSTEM}", encoding="utf-8")
        agent = folder / "agent.yaml"
        agent.write_text(json.dumps({"version": 1, "agent": {"name": "avs-prompt", "system_prompt_path": "./system.md",
                         "system_prompt_args": {"AVS_SYSTEM": request.system}, "tools": [], "subagents": {}}}), encoding="utf-8")
        skills = folder / "skills"
        skills.mkdir()
        args = executable + ["--print", "--agent-file", str(agent), "--config-file", str(config),
                             "--mcp-config-file", str(mcp), "--skills-dir", str(skills), "--model", s["model"],
                             "--input-format", "stream-json", "--output-format", "stream-json", "--final-message-only"]
        if s['reasoning'] != 'auto':
            args += ['--thinking' if s['reasoning'] == 'thinking' else '--no-thinking']
        message = {"role": "user", "content": image_content(request, provider)}
    return args, (json.dumps(message, ensure_ascii=False) + "\n").encode()


def parse_output(provider, stdout):
    events = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    if provider == "claude":
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        if result.get("is_error") or result.get("subtype") != "success":
            raise ValueError("Claude did not return a successful final result")
        text, counts = result.get("result", ""), result.get("usage", {})
    else:
        result = next((e for e in reversed(events) if e.get("role") == "assistant"), {})
        if result.get("tool_calls"):
            raise ValueError("Kimi requested a tool despite the tool-free agent configuration")
        content = result.get("content", "")
        text = content if isinstance(content, str) else "".join(p.get("text", "") for p in content if p.get("type") == "text")
        counts = {}
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{provider} returned no final text")
    return {"text": text, "usage": {k: counts.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")}}


async def generate(request):
    provider = request.settings["adapter"]
    executable = await asyncio.to_thread(capabilities, provider)
    with tempfile.TemporaryDirectory(prefix=f"avs-{provider}-") as directory:
        args, stdin = prepare(request, directory, executable)
        process = await asyncio.to_thread(subprocess.Popen, args, cwd=directory, stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        communication = asyncio.create_task(asyncio.to_thread(process.communicate, stdin))
        try:
            stdout, _ = await asyncio.wait_for(asyncio.shield(communication), request.settings["timeout"])
        except (asyncio.CancelledError, asyncio.TimeoutError):
            process.kill()
            await communication
            raise
        if process.returncode:
            raise ValueError(f"{provider} CLI failed (exit {process.returncode}). Check server login, model and CLI version; no automatic retry was made")
        return {**parse_output(provider, stdout), "provider": provider, "model": request.settings["model"]}
