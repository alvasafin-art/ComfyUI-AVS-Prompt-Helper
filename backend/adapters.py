"""API and CLI dispatch, with no plugin retries of ambiguous chargeable requests."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import aiohttp


def usage(data):
    source = data.get("usage") or {}
    return {key: source.get(key, source.get(alias)) for key, alias in
            [("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens")]}


def payload(request, mode):
    s = request.settings
    content = [{"type": "input_text" if mode == "responses" else "text", "text": request.user}]
    for image in request.images:
        content.append({"type": "input_text" if mode == "responses" else "text", "text": f"Image @{image.label}:"})
        uri = "data:" + image.mime + ";base64," + base64.b64encode(image.data).decode()
        content.append({"type": "input_image", "image_url": uri} if mode == "responses" else
                       {"type": "image_url", "image_url": {"url": uri}})
    if mode == "responses":
        body = {"model": s["model"], "instructions": request.system, "input": [{"role": "user", "content": content}],
                "max_output_tokens": s["max_output_tokens"], "store": False}
        if s["reasoning"] != "auto":
            body["reasoning"] = {"effort": s["reasoning"]}
    else:
        body = {"model": s["model"], "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": content}],
                "max_tokens": s["max_output_tokens"]}
        if s["reasoning"] != "auto":
            body["reasoning_effort"] = s["reasoning"]
    return body


async def api_generate(request):
    s = request.settings
    native = s["adapter"] == "openai"
    key = os.environ.get("OPENAI_API_KEY" if native else "AVS_COMPATIBLE_API_KEY", "")
    if native and not key:
        raise ValueError("OPENAI_API_KEY is missing in the ComfyUI server environment")
    base = "https://api.openai.com/v1" if native else s["base_url"].rstrip("/")
    mode = "responses" if native or s["api_mode"] == "auto" else s["api_mode"]
    headers = {"Authorization": "Bearer " + key} if key else {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=s["timeout"]), headers=headers) as session:
        # Only a definite missing endpoint permits fallback; never retry timeouts/5xx.
        for attempt in range(2):
            endpoint = "/responses" if mode == "responses" else "/chat/completions"
            async with session.post(base + endpoint, json=payload(request, mode), allow_redirects=False) as response:
                if response.status in (404, 405) and not native and s["api_mode"] == "auto" and attempt == 0:
                    mode = "chat"
                    continue
                if response.status >= 300:
                    # Do not echo arbitrary provider bodies: they may contain keys/request images.
                    explanations = {401: "Authentication failed", 403: "Access denied", 429: "Rate limit or quota exceeded",
                                    400: "Unsupported model, reasoning effort, image payload or generation parameter", 404: "Model or endpoint not found"}
                    raise ValueError(f"Provider HTTP {response.status}: {explanations.get(response.status, 'Request failed')}. Check Settings and provider capabilities; no automatic retry was made.")
                data = await response.json()
                if mode == "responses":
                    if data.get("status") not in (None, "completed"):
                        raise ValueError("Provider returned an incomplete response; increase output limit or check model")
                    text = "".join(c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                                   for c in item.get("content", []) if c.get("type") == "output_text")
                else:
                    choices = data.get("choices", [])
                    if not choices or choices[0].get("finish_reason") not in (None, "stop"):
                        raise ValueError("Provider returned a partial/unsupported response")
                    text = choices[0].get("message", {}).get("content", "")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Provider returned no final text")
                return {"text": text, "usage": usage(data), "provider": s["adapter"], "model": s["model"]}


def cli_executable():
    configured = os.environ.get("AVS_CODEX_EXECUTABLE", "codex")
    exe = shutil.which(configured)
    if not exe:
        raise ValueError("Codex executable missing; set AVS_CODEX_EXECUTABLE on the server")
    # npm Windows shims require a shell; resolve the native binary instead.
    if Path(exe).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        candidates = list((Path(exe).parent / "node_modules" / "@openai").glob("codex*/**/codex.exe"))
        if not candidates:
            raise ValueError("Set AVS_CODEX_EXECUTABLE to the native codex.exe (not a shell shim)")
        exe = str(candidates[0])
    return exe


def cli_capabilities():
    exe = cli_executable()
    result = subprocess.run([exe, "exec", "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, shell=False)
    required = ["--sandbox", "--output-last-message", "--image", "--ignore-user-config", "--ignore-rules", "--ephemeral"]
    if result.returncode or any(flag not in result.stdout for flag in required):
        raise ValueError("Codex version lacks required isolation flags; update Codex CLI")
    return exe


async def cli_generate(request):
    s = request.settings
    image = request.image
    if image:
        from .image_cli import discover, generated_png, cancelled
        catalog = await asyncio.to_thread(discover)
        model = next((entry for entry in catalog["models"] if entry["id"] == s["model"]), None)
        if not model:
            raise ValueError("The selected language model is unavailable in the server's Codex catalogue")
        if s["reasoning"] != "auto" and s["reasoning"] not in model["reasoning"]:
            raise ValueError("The selected reasoning effort is unavailable for this server model")
        if image.id and cancelled(image.id):
            raise asyncio.CancelledError()
        exe = cli_executable()
    else:
        exe = await asyncio.to_thread(cli_capabilities)
    with tempfile.TemporaryDirectory(prefix="avs-prompt-") as directory:
        out = Path(directory) / "answer.txt"
        args = [exe, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--sandbox", "read-only",
                "--skip-git-repo-check", "--color", "never", "--json", "--model", s["model"],
                "--output-last-message", str(out), "-c", 'approval_policy="never"',
                "-c", "features.shell_tool=false", "-c", "features.unified_exec=false",
                "-c", 'web_search="disabled"']
        args += ["--enable" if image else "--disable", "image_generation"]
        if s["reasoning"] != "auto":
            args += ["-c", "model_reasoning_effort=" + json.dumps(s["reasoning"])]
        for index, attachment in enumerate(request.images):
            path = Path(directory) / f"image_{index+1}.png"
            path.write_bytes(attachment.data)
            args += ["--image", str(path)]
        args += ["-"]
        prompt = (image.instruction() if image else "Return only the final requested text. Do not use tools or inspect files.")
        prompt += "\n\nSYSTEM INSTRUCTIONS:\n" + request.system
        prompt += "\n\nUSER INSTRUCTIONS:\n" + request.user
        if request.images:
            prompt += "\n\nAttached images in order: " + ", ".join("@" + i.label for i in request.images)
        # Popen in a worker supports Windows ComfyUI selector event loops too.
        start = asyncio.create_task(asyncio.to_thread(subprocess.Popen, args, cwd=directory, stdin=subprocess.PIPE,
                                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False))
        try:
            process = await asyncio.shield(start)
        except asyncio.CancelledError:
            process = await start
            process.kill()
            await asyncio.to_thread(process.communicate)
            raise
        communication = asyncio.create_task(asyncio.to_thread(process.communicate, prompt.encode()))
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), s["timeout"])
        except (asyncio.CancelledError, asyncio.TimeoutError):
            process.kill()
            stdout, _ = await communication
            if image:
                generated_png(stdout, required=False)
            raise
        if process.returncode:
            if image:
                generated_png(stdout, required=False)
                raise ValueError("Codex image generation failed. Check the model, server-side sign-in and account access.")
            from .codex_catalog import failure_detail
            detail = failure_detail(stdout, stderr, (request.user, request.system))
            raise ValueError(f"Codex failed (exit {process.returncode}): {detail}")
        png = generated_png(stdout) if image else None
        text = out.read_text(encoding="utf-8").strip() if out.exists() else ""
        if not text:
            raise ValueError("Codex returned no final text")
        counts = {}
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
                if event.get("type") == "turn.completed":
                    counts = usage(event)
            except ValueError:
                pass
        result = {"text": text, "usage": counts, "provider": "codex", "model": s["model"]}
        if png is not None:
            result["image"] = png
        return result


async def generate(request):
    try:
        if request.settings["adapter"] in {"claude", "kimi"}:
            from .extra_cli import generate as extra_generate
            return await extra_generate(request)
        return await (cli_generate(request) if request.settings["adapter"] == "codex" else api_generate(request))
    except asyncio.TimeoutError as exc:
        raise ValueError("Provider timed out; not retried because it may already have processed the request") from exc
    except aiohttp.ClientError as exc:
        raise ValueError("Provider connection failed; verify server URL/network. Request was not retried.") from exc
