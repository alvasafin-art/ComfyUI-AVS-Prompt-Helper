"""Atomic storage. Image handles are random capabilities, never filesystem paths."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid

LOCK = threading.RLock()


def root():
    configured = os.environ.get("AVS_PROMPT_HELPER_DATA")
    if configured:
        path = Path(configured)
    else:
        try:
            import folder_paths
            path = Path(folder_paths.get_user_directory()) / "avs_prompt_helper"
        except ImportError:
            path = Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def asset_path(handle):
    if not isinstance(handle, str) or not re.fullmatch(r"[a-f0-9]{64}", handle):
        raise ValueError("Invalid attachment ID")
    return root() / "uploads" / (handle + ".png")


def presets(user, operation=None, data=None):
    path = root() / "presets" / (hashlib.sha256(user.encode()).hexdigest() + ".json")
    with LOCK:
        store = read_json(path, {"version": 1, "presets": []})
        if not isinstance(store, dict) or not isinstance(store.get("presets"), list):
            store = {"version": 1, "presets": []}
        if operation:
            data = data or {}
            ident = data.get("id") or uuid.uuid4().hex
            if operation == "save":
                name, prompt = data.get("name", "").strip(), data.get("system_prompt", "")
                if not name or len(name) > 120 or not isinstance(prompt, str) or len(prompt) > 100000:
                    raise ValueError("Preset requires a name (1–120 characters) and valid text")
                item = {"id": ident, "name": name, "system_prompt": prompt}
                store["presets"] = [p for p in store["presets"] if p.get("id") != ident] + [item]
            elif operation == "delete":
                store["presets"] = [p for p in store["presets"] if p.get("id") != ident]
            else:
                raise ValueError("Unknown preset operation")
            if len(store["presets"]) > 1000:
                raise ValueError("Preset library limit: 1000")
            atomic_json(path, store)
        return store
