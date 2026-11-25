import asyncio
import secrets
from urllib.parse import urlparse
from aiohttp import web
import aiohttp
from .storage import presets, asset_path
from .images import decode, encode, MAX_BYTES
from .request import settings_for
from .adapters import cli_capabilities
from .image_access import register_prompt_access, rejection


def register(server):
    routes = server.routes
    register_prompt_access(server)

    def user(request):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Cross-origin AVS request rejected")
        return server.user_manager.get_request_user_id(request)

    async def guarded(request, action):
        try:
            user(request)
            return await action()
        except (ValueError, KeyError, OSError, asyncio.TimeoutError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.get("/avs-prompt/presets")
    async def get_presets(request):
        async def action():
            return web.json_response(await asyncio.to_thread(presets, user(request)))
        return await guarded(request, action)

    @routes.post("/avs-prompt/presets")
    async def set_presets(request):
        async def action():
            body = await request.json()
            return web.json_response(await asyncio.to_thread(presets, user(request), body.get("operation"), body))
        return await guarded(request, action)

    @routes.post("/avs-prompt/upload")
    async def upload(request):
        async def action():
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != "image":
                raise ValueError("Expected multipart image")
            data = bytearray()
            while chunk := await part.read_chunk():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError("Upload exceeds 25 MiB")
            def save():
                encoded, width, height = encode(decode(bytes(data)))
                handle = secrets.token_hex(32)
                path = asset_path(handle)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(encoded)
                return {"id": handle, "width": width, "height": height}
            return web.json_response(await asyncio.to_thread(save))
        return await guarded(request, action)

    @routes.get("/avs-prompt/assets/{handle}")
    async def asset(request):
        async def action():
            path = asset_path(request.match_info["handle"])
            if not path.exists():
                raise web.HTTPNotFound(text="Missing attachment; re-upload")
            return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})
        return await guarded(request, action)

    @routes.post("/avs-prompt/test")
    async def test(request):
        async def action():
            import os
            supplied = await request.json()
            # Discovery must work before a model has been selected.
            s = settings_for({"settings": {**supplied, "model": supplied.get("model") or "discovery", "reasoning": "auto"}})
            if s["adapter"] in {"claude", "kimi"}:
                from .cli_catalog import discover
                return web.json_response(await asyncio.to_thread(discover, s["adapter"]))
            if s["adapter"] == "codex":
                from .codex_catalog import discover
                exe = await asyncio.to_thread(cli_capabilities)
                return web.json_response(await asyncio.to_thread(discover, exe))
            native = s["adapter"] == "openai"
            key = os.environ.get("OPENAI_API_KEY" if native else "AVS_COMPATIBLE_API_KEY", "")
            if native and not key:
                raise ValueError("OPENAI_API_KEY missing on server")
            base = "https://api.openai.com/v1" if native else s["base_url"].rstrip("/")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(base + "/models", headers={"Authorization": "Bearer " + key} if key else {}, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ValueError(f"Models endpoint HTTP {response.status}; configure endpoint/model manually")
                    data = await response.json()
                    models = [{"id": m["id"], "name": m["id"], "reasoning": None}
                              for m in data.get("data", []) if isinstance(m.get("id"), str)]
                    return web.json_response({"message": "Connected. Model list loaded; this API does not report reasoning capabilities.", "models": models})
        return await guarded(request, action)

    @routes.get("/avs-prompt/image-cli")
    async def image_cli(request):
        from .image_cli import discover

        async def action():
            if reason := rejection(request):
                return web.json_response({"error": reason}, status=403)
            try:
                return web.json_response(await asyncio.to_thread(discover))
            except (OSError, asyncio.TimeoutError):
                raise ValueError("Unable to run Codex CLI discovery on the ComfyUI server") from None
        return await guarded(request, action)

    @routes.post("/avs-prompt/image-cli/cancel/{identifier}")
    async def cancel_image_cli(request):
        from .image_cli import cancel

        async def action():
            if reason := rejection(request):
                return web.json_response({"error": reason}, status=403)
            cancel(request.match_info["identifier"])
            return web.Response(status=204)
        return await guarded(request, action)
