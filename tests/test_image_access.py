import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from backend.image_access import (
    AuthorizedPrompt, DENIED, DISABLED, register_prompt_access, rejection, require_authorized
)


def client(peer, local, headers=None):
    endpoints = {"peername": (peer, 10240), "sockname": (local, 8188)}
    return SimpleNamespace(transport=SimpleNamespace(get_extra_info=endpoints.get), headers=headers or {})


def test_only_direct_local_and_explicit_network_clients_are_admitted(tmp_path, monkeypatch):
    monkeypatch.delenv("AVS_ENABLE_CODEX_IMAGE", raising=False)
    assert rejection(client("127.0.0.1", "127.0.0.1")) is None
    assert rejection(client("::1", "::1")) is None
    assert rejection(client("::ffff:192.168.1.10", "192.168.1.10")) is None
    assert rejection(client("192.168.1.11", "192.168.1.10")) == DENIED
    assert rejection(client("127.0.0.1", "127.0.0.1", {"Forwarded": "for=192.168.1.11"})) == DENIED
    (tmp_path / "enable-codex-image").touch()
    monkeypatch.setenv("AVS_ENABLE_CODEX_IMAGE", "1")
    assert rejection(client("192.168.1.11", "192.168.1.10")) == DENIED
    config = tmp_path / "trusted-codex-image-clients.txt"
    config.write_text("192.168.1.0/24 # workshop\n", encoding="utf-8")
    assert rejection(client("192.168.1.11", "192.168.1.10")) is None
    assert rejection(client("192.168.2.11", "192.168.1.10")) == DENIED
    config.write_text("0.0.0.0/0\n", encoding="utf-8")
    assert rejection(client("192.168.1.11", "192.168.1.10")) == DENIED
    monkeypatch.setenv("AVS_ENABLE_CODEX_IMAGE", "0")
    assert rejection(client("127.0.0.1", "127.0.0.1")) == DISABLED


@pytest.mark.asyncio
async def test_prompt_middleware_blocks_images_and_preserves_text(monkeypatch):
    monkeypatch.delenv("AVS_ENABLE_CODEX_IMAGE", raising=False)
    app = web.Application()
    handlers = []
    register_prompt_access(SimpleNamespace(app=app, add_on_prompt_handler=handlers.append))

    async def submit(request):
        payload = await request.json()
        for handler in handlers:
            payload = handler(payload)
        original_prompt = payload["prompt"]
        try:
            require_authorized(original_prompt)
        except ValueError:
            return web.json_response({"authorized": False})
        return web.json_response({"authorized": True})

    app.router.add_post("/prompt", submit)
    app.router.add_post("/api/prompt", submit)

    def workflow(mode):
        state = json.dumps({"settings": {"output_mode": mode}})
        return {"prompt": {"1": {"class_type": "AVSPromptHelper", "inputs": {"state": state}}}}

    async with TestClient(TestServer(app)) as http:
        assert await (await http.post("/prompt", json=workflow("text_and_image"))).json() == {"authorized": True}
        headers = {"X-Forwarded-For": "127.0.0.1"}
        for path in ("/prompt", "/api/prompt"):
            async with http.post(path, json=workflow("text_and_image"), headers=headers) as response:
                assert response.status == 403
            assert await (await http.post(path, json=workflow("text"), headers=headers)).json() == {"authorized": False}
        with pytest.raises(ValueError, match="local clients"):
            require_authorized({"authorized": True})
        require_authorized(AuthorizedPrompt())
