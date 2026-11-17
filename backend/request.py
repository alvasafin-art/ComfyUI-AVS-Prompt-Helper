import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .images import collect

DEFAULTS = dict(adapter="openai", model="", base_url="", api_mode="chat", reasoning="auto",
                merge_mode="append", image_mode="original", max_mp=1.0, timeout=120,
                max_images=32, max_output_tokens=2048)


def parse_state(raw):
    state = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(state, dict) or state.get("version", 1) != 1:
        raise ValueError("Unsupported AVS workflow state version")
    if len(json.dumps(state)) > 500000:
        raise ValueError("Node state exceeds 500 KB")
    return state


def settings_for(state):
    settings = {**DEFAULTS, **{k: v for k, v in state.get("settings", {}).items() if k in DEFAULTS}}
    if settings["adapter"] not in {"openai", "compatible", "codex", "claude", "kimi"}:
        raise ValueError("Unsupported adapter")
    if not isinstance(settings["model"], str) or not settings["model"].strip():
        raise ValueError("Open Settings and enter a model ID")
    efforts = {"auto", "thinking", "no_thinking"} if settings["adapter"] == "kimi" else {"auto", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    if settings["reasoning"] not in efforts:
        raise ValueError("Unknown reasoning effort")
    if settings["merge_mode"] not in {"append", "replace", "prepend"}:
        raise ValueError("Unknown text merge mode")
    if settings["api_mode"] not in {"chat", "responses", "auto"}:
        raise ValueError("Unknown API compatibility mode")
    for key, low, high in [("timeout", 5, 1800), ("max_images", 1, 100), ("max_output_tokens", 16, 100000)]:
        settings[key] = int(settings[key])
        if not low <= settings[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    if settings["adapter"] == "compatible":
        url = urlparse(settings["base_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Base URL must be an HTTP(S) URL without credentials, query or fragment")
    return settings


def render_prompt(state, images):
    aliases = {image.stable_id: image.label for image in images}
    parts = state.get("document", [state.get("prompt", "")])
    if not isinstance(parts, list):
        raise ValueError("Prompt document must be a list")
    result = []
    for part in parts:
        if isinstance(part, str):
            result.append(part)
        elif isinstance(part, dict) and part.get("image_id") in aliases:
            result.append("@" + aliases[part["image_id"]])
        else:
            raise ValueError("Dangling image mention; remove it or reconnect its original image")
    text = "".join(result)
    for number in re.findall(r"@image_(\d+)\b", text):
        if not 1 <= int(number) <= len(images):
            raise ValueError(f"Dangling mention @image_{number}")
    return text


@dataclass
class PromptRequest:
    user: str
    system: str
    images: list
    settings: dict

    def fingerprint(self):
        semantic = {"version": 1, "user": self.user, "system": self.system,
                    "settings": self.settings,
                    "images": [{"label": i.label, "sha256": i.digest} for i in self.images]}
        return hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def build(state, external="", **inputs):
    settings = settings_for(state)
    images = collect(state, inputs, settings)
    internal = render_prompt(state, images)
    mode = settings["merge_mode"]
    user = external if mode == "replace" and external else "\n\n".join(p for p in ([external, internal] if mode == "prepend" else [internal, external]) if p)
    if not user.strip():
        raise ValueError("Your Prompt or external text is required")
    return PromptRequest(user, str(state.get("system_prompt", "")), images, settings)
