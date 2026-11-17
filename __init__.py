from .nodes import AVSPromptHelper

NODE_CLASS_MAPPINGS = {"AVSPromptHelper": AVSPromptHelper}
NODE_DISPLAY_NAME_MAPPINGS = {"AVSPromptHelper": "AVS Prompt Helper"}
WEB_DIRECTORY = "./web"

try:
    from server import PromptServer
except ImportError:
    PromptServer = None
if PromptServer is not None and hasattr(PromptServer, "instance"):
    from .backend.routes import register
    register(PromptServer.instance)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
