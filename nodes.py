import asyncio
from .backend.request import parse_state, build
from .backend.cache import execute
from .backend.adapters import generate
from .backend.storage import asset_path


class AVSPromptHelper:
    CATEGORY = "AVS/Prompt"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"state": ("STRING", {"default": '{"version":1}', "multiline": True})},
                "optional": {"external_text": ("STRING", {"forceInput": True}),
                             **{f"image_{i}": ("IMAGE",) for i in range(1, 21)}},
                "hidden": {"unique_id": "UNIQUE_ID"}}

    @classmethod
    def IS_CHANGED(cls, state, **kwargs):
        # Include attachment bytes: missing/replaced assets must invalidate Comfy's cache.
        import hashlib
        digest = hashlib.sha256(state.encode())
        for handle in parse_state(state).get("uploads", []):
            path = asset_path(handle)
            digest.update(path.read_bytes() if path.exists() else b"missing")
        return digest.hexdigest()

    async def run(self, state, external_text="", unique_id=None, **images):
        parsed = parse_state(state)
        request = await asyncio.to_thread(build, parsed, external_text, **images)
        task = asyncio.create_task(execute(request, str(parsed.get("regeneration", "")), generate))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.25)
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
        status = {key: value for key, value in result.items() if key != "text"}
        return {"ui": {"avs_status": [status]}, "result": (result["text"],)}
