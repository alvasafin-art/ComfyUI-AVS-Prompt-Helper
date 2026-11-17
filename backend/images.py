import hashlib
import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from .storage import asset_path

MAX_PIXELS = 80_000_000
MAX_BYTES = 25 * 1024 * 1024


@dataclass
class ImageItem:
    stable_id: str
    label: str
    data: bytes
    width: int
    height: int
    mime: str = "image/png"

    @property
    def digest(self):
        return hashlib.sha256(self.data).hexdigest()


def decode(data):
    if len(data) > MAX_BYTES:
        raise ValueError("Image exceeds 25 MiB upload limit")
    image = Image.open(io.BytesIO(data))
    if image.format not in {"PNG", "JPEG", "WEBP"}:
        raise ValueError("Supported formats: PNG, JPEG, WebP")
    if image.width * image.height > MAX_PIXELS:
        raise ValueError("Image exceeds 80 megapixels")
    if getattr(image, "n_frames", 1) > 1:
        raise ValueError("Animated images are unsupported; upload a single frame")
    return ImageOps.exif_transpose(image).convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")


def encode(image, mode="original", max_mp=1.0):
    if mode not in {"original", "max_mp"}:
        raise ValueError("Unknown image size mode")
    if mode == "max_mp":
        if not math.isfinite(float(max_mp)) or float(max_mp) <= 0:
            raise ValueError("Maximum megapixels must be positive")
        ceiling = max(1, int(float(max_mp) * 1_000_000))
        if image.width * image.height > ceiling:
            scale = math.sqrt(ceiling / (image.width * image.height))
            width, height = max(1, int(image.width * scale)), max(1, int(image.height * scale))
            while width * height > ceiling:
                if width >= height:
                    width -= 1
                else:
                    height -= 1
            image = image.resize((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), image.width, image.height


def tensor_image(tensor):
    shape = tuple(tensor.shape)
    if len(shape) != 4 or shape[0] != 1 or shape[-1] not in (1, 3, 4):
        raise ValueError("Each IMAGE socket requires a single image [1,H,W,1/3/4]; split batches upstream")
    if shape[1] * shape[2] > MAX_PIXELS:
        raise ValueError("Image exceeds 80 megapixels")
    data = tensor.detach().float().cpu().numpy() if hasattr(tensor, "detach") else np.asarray(tensor)
    if not np.isfinite(data).all():
        raise ValueError("IMAGE contains NaN or infinity")
    data = np.rint(np.clip(data[0], 0, 1) * 255).astype(np.uint8)
    if data.shape[-1] == 1:
        data = data[:, :, 0]
    return Image.fromarray(data).convert("RGBA" if shape[-1] == 4 else "RGB")


def collect(state, inputs, settings):
    sources = []
    for index in range(1, 21):
        name = f"image_{index}"
        if inputs.get(name) is not None:
            sources.append(("socket:" + name, tensor_image(inputs[name])))
    for handle in state.get("uploads", []):
        path = asset_path(handle)
        if not path.is_file():
            raise ValueError(f"Missing attachment {handle[:12]}; re-upload or migrate the uploads directory")
        sources.append(("upload:" + handle, decode(path.read_bytes())))
    if len(sources) > settings["max_images"]:
        raise ValueError(f"Request has {len(sources)} images; configured provider limit is {settings['max_images']}")
    result = []
    for stable_id, image in sources:
        data, width, height = encode(image, settings["image_mode"], settings["max_mp"])
        result.append(ImageItem(stable_id, f"image_{len(result)+1}", data, width, height))
    if sum(len(i.data) for i in result) > 40 * 1024 * 1024:
        raise ValueError("Combined image payload exceeds 40 MiB; use Maximum megapixels")
    return result
