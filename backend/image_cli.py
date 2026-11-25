"""Typed request and result handling for the server's built-in Codex image tool."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import UUID

from .images import MAX_BYTES, decode, encode

PROTOCOL = 1
VERSION = "0.4.3"
SIZES = {(1024, 1024): "square (1:1)", (1536, 1024): "landscape (3:2)", (1024, 1536): "portrait (2:3)"}
_cancelled = {}
_lock = threading.Lock()


def request_id(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Invalid AVS image request ID")
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("Invalid AVS image request ID") from None


@dataclass(frozen=True)
class ImageRequest:
    operation: str
    width: int
    height: int
    id: str | None = None

    @classmethod
    def parse(cls, raw):
        if raw is None:  # The ComfyUI settings dialog defaults to square generation.
            return cls("generate", 1024, 1024)
        if not isinstance(raw, dict) or set(raw) != {"version", "operation", "width", "height", "request_id"}:
            raise ValueError("Invalid AVS image request fields")
        if type(raw["version"]) is not int or raw["version"] != PROTOCOL:
            raise ValueError("Unsupported AVS image request version")
        width, height = raw["width"], raw["height"]
        if type(width) is not int or type(height) is not int or (width, height) not in SIZES:
            raise ValueError("Unsupported AVS image request dimensions")
        if raw["operation"] not in ("generate", "edit"):
            raise ValueError("Unsupported AVS image operation")
        return cls(raw["operation"], width, height, request_id(raw["request_id"]))

    def instruction(self):
        action = ("Edit the first attached image following the request." if self.operation == "edit"
                  else "Generate a new image, using any attachments as references.")
        return (f"Call the built-in image generation tool exactly once for a {SIZES[self.width, self.height]} image. "
                f"{action} Use no other tools or files. Then return a brief text response.")


def cancel(identifier):
    identifier = request_id(identifier)
    now = time.monotonic()
    with _lock:
        for expired in [key for key, expiry in _cancelled.items() if expiry <= now]:
            del _cancelled[expired]
        if len(_cancelled) >= 4096 and identifier not in _cancelled:
            raise ValueError("Too many recent image cancellations")
        _cancelled[identifier] = now + 1800


def cancelled(identifier):
    with _lock:
        return _cancelled.get(identifier, 0) > time.monotonic()


def discover():
    from .adapters import cli_capabilities
    from .codex_catalog import discover as discover_models

    exe = cli_capabilities()
    with subprocess.Popen([exe, "features", "list"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, encoding="utf-8", errors="replace", shell=False) as process:
        try:
            features, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ValueError("Codex feature discovery timed out on the ComfyUI server") from None
    if process.returncode or not any(row.split()[:1] == ["image_generation"] for row in features.splitlines()):
        raise ValueError("The server's Codex CLI does not support built-in image generation. Update Codex CLI.")
    result = discover_models(exe)
    return {**result, "version": VERSION, "protocol": PROTOCOL, "adapter": "codex",
            "image_tool": "image_generation"}


def generated_png(stdout, required=True):
    thread = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get("type") == "thread.started":
                thread = request_id(event.get("thread_id"))
                break
        except ValueError:
            continue
    if thread is None:
        if required:
            raise ValueError("Codex returned no image generation session")
        return None
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    directory = home / "generated_images" / thread
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or directory.resolve().parent != (home / "generated_images").resolve():
        raise ValueError("Invalid Codex image output folder")
    files = [p for p in directory.glob("exec-*.png") if not p.is_symlink() and p.is_file()]
    try:
        if not required:
            return None
        if len(files) != 1:
            raise ValueError("Codex did not return exactly one generated PNG")
        if files[0].stat().st_size > MAX_BYTES:
            raise ValueError("Codex returned an image larger than 25 MiB")
        return encode(decode(files[0].read_bytes()))[0]
    finally:
        for path in files:
            path.unlink(missing_ok=True)
