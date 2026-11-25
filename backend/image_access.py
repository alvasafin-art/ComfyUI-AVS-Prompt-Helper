"""Authorize the network peer before an image workflow reaches the executor."""
from contextvars import ContextVar
from ipaddress import ip_address, ip_network
import json
import os

from aiohttp import web
from .storage import root

DENIED = ("Codex image generation is available to local clients and clients listed in "
          "trusted-codex-image-clients.txt on the ComfyUI server.")
DISABLED = "Codex image generation is disabled on this server by AVS_ENABLE_CODEX_IMAGE=0."
_trusted_submission = ContextVar("avs_trusted_submission", default=False)


class AuthorizedPrompt(dict):
    """Server-created prompt. JSON clients cannot supply this type."""


def _address(endpoint):
    try:
        address = ip_address(endpoint[0])
    except (IndexError, TypeError, ValueError):
        return None
    return getattr(address, "ipv4_mapped", None) or address


def _trusted_networks():
    path = root() / "trusted-codex-image-clients.txt"
    try:
        with path.open(encoding="utf-8") as config:
            text = config.read(8193)
        if len(text) > 8192:
            return ()
        entries = [line.partition("#")[0].strip() for line in text.splitlines()]
        networks = tuple(ip_network(entry, strict=True) for entry in entries if entry)
        return networks if all(network.prefixlen > 0 for network in networks) else ()
    except (OSError, ValueError):
        return ()


def rejection(request):
    if os.environ.get("AVS_ENABLE_CODEX_IMAGE") == "0":
        return DISABLED
    transport = request.transport
    peer = _address(transport.get_extra_info("peername")) if transport else None
    local = _address(transport.get_extra_info("sockname")) if transport else None
    if peer is None or any(name in request.headers for name in ("Forwarded", "X-Forwarded-For", "X-Real-IP")):
        return DENIED
    if peer.is_loopback or peer == local or any(peer in network for network in _trusted_networks()):
        return None
    return DENIED


def _has_literal_image_request(payload):
    graph = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(graph, dict):
        return False
    for node in graph.values():
        if not isinstance(node, dict) or node.get("class_type") != "AVSPromptHelper":
            continue
        inputs = node.get("inputs")
        state = inputs.get("state") if isinstance(inputs, dict) else None
        if not isinstance(state, str):
            continue
        try:
            state = json.loads(state)
        except ValueError:
            continue
        settings = state.get("settings") if isinstance(state, dict) else None
        if isinstance(settings, dict) and settings.get("output_mode") == "text_and_image":
            return True
    return False


def register_prompt_access(server):
    @web.middleware
    async def check_prompt(request, handler):
        if request.method != "POST" or request.path not in ("/prompt", "/api/prompt"):
            return await handler(request)
        reason = rejection(request)
        if reason:
            # aiohttp caches the request body for the original prompt handler.
            try:
                payload = await request.json()
            except (ValueError, UnicodeError):
                pass
            else:
                if _has_literal_image_request(payload):
                    return web.json_response({"error": reason}, status=403)
        token = _trusted_submission.set(reason is None)
        try:
            return await handler(request)
        finally:
            _trusted_submission.reset(token)

    def authorize(payload):
        if _trusted_submission.get() and isinstance(payload, dict) and isinstance(payload.get("prompt"), dict):
            payload["prompt"] = AuthorizedPrompt(payload["prompt"])
        return payload

    server.app.middlewares.append(check_prompt)
    server.add_on_prompt_handler(authorize)


def require_authorized(prompt):
    if os.environ.get("AVS_ENABLE_CODEX_IMAGE") == "0":
        raise ValueError(DISABLED)
    if not isinstance(prompt, AuthorizedPrompt):
        raise ValueError(DENIED)
