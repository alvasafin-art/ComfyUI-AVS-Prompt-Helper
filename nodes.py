import asyncio
import io
import time
from .backend.request import parse_state, build
from .backend.cache import execute
from .backend.adapters import generate
from .backend.storage import asset_path
from .backend.image_cli import cancelled
from .backend.image_access import require_authorized


class AVSPromptHelper:
    CATEGORY = "AVS/Prompt"
    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("prompt", "image")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"state": ("STRING", {"default": '{"version":1}', "multiline": True})},
                "optional": {"external_text": ("STRING", {"forceInput": True}),
                             **{f"image_{i}": ("IMAGE",) for i in range(1, 21)}},
                "hidden": {"unique_id": "UNIQUE_ID", "prompt": "PROMPT"}}

    @classmethod
    def IS_CHANGED(cls, state, **kwargs):
        # Include attachment bytes: missing/replaced assets must invalidate Comfy's cache.
        import hashlib
        digest = hashlib.sha256(state.encode())
        for handle in parse_state(state).get("uploads", []):
            path = asset_path(handle)
            digest.update(path.read_bytes() if path.exists() else b"missing")
        return digest.hexdigest()

    async def run(self, state, external_text="", unique_id=None, prompt=None, **images):
        parsed = parse_state(state)
        request = await asyncio.to_thread(build, parsed, external_text, **images)
        if request.image:
            require_authorized(prompt)
            if request.image.id and cancelled(request.image.id):
                raise ValueError("AVS image request cancelled")
        started = time.monotonic()
        # The persistent text cache never stores image bytes.
        task = asyncio.create_task(generate(request) if request.image else
                                   execute(request, str(parsed.get("regeneration", "")), generate))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.25)
                if request.image and request.image.id and cancelled(request.image.id):
                    raise ValueError("AVS image request cancelled")
                try:
                    from comfy.model_management import throw_exception_if_processing_interrupted
                except ImportError:
                    pass
                else:
                    throw_exception_if_processing_interrupted()
            result = await task
        except BaseException:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            raise
        image = None
        if request.image:
            import numpy as np
            import torch
            from PIL import Image
            with Image.open(io.BytesIO(result["image"])) as rendered:
                image = torch.from_numpy(np.asarray(rendered.convert("RGB"), dtype=np.float32) / 255.0).unsqueeze(0)
            result["duration"] = round(time.monotonic() - started, 2)
        status = {key: value for key, value in result.items() if key not in {"text", "image"}}
        return {"ui": {"avs_status": [status]}, "result": (result["text"], image)}
