import io
import json
from uuid import uuid4

import pytest
from PIL import Image

from backend.image_cli import ImageRequest, cancel, cancelled, generated_png
from backend.request import build


def test_old_state_keeps_text_mode_and_image_request_requires_codex():
    state = {"prompt": "fixture", "settings": {"adapter": "openai", "model": "fixture"}}
    assert build(state).image is None
    state["settings"]["output_mode"] = "text_and_image"
    with pytest.raises(ValueError, match="requires Codex"):
        build(state)


def test_typed_request_validates_operation_dimensions_version_and_fields():
    fields = dict(version=1, operation="generate", width=1536, height=1024, request_id=str(uuid4()))
    image = ImageRequest.parse(fields)
    assert "landscape" in image.instruction()
    for overrides in (dict(version=True), dict(width=-1), dict(operation="shell"), dict(executable="abc")):
        with pytest.raises(ValueError):
            ImageRequest.parse({**fields, **overrides})
    state = {"prompt": "fixture", "settings": {"adapter": "codex", "model": "fixture", "output_mode": "text_and_image"},
             "image_request": {**fields, "operation": "edit"}}
    with pytest.raises(ValueError, match="requires a source"):
        build(state)


def test_cancellation_is_scoped():
    identifier = str(uuid4())
    cancel(identifier)
    assert cancelled(identifier)
    assert not cancelled(str(uuid4()))


def test_extracts_only_the_threads_generated_png_and_cleans_it_up(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    thread = str(uuid4())
    location = tmp_path / "generated_images" / thread
    location.mkdir(parents=True)
    generated = location / "exec-image.png"
    Image.new("RGB", (3, 2), "orange").save(generated)
    untouched = location / "unrelated.png"
    untouched.touch()
    event = json.dumps({"type": "thread.started", "thread_id": thread}).encode()
    with Image.open(io.BytesIO(generated_png(event))) as image:
        assert image.size == (3, 2)
    assert not generated.exists()
    assert untouched.exists()
    with pytest.raises(ValueError, match="exactly one"):
        generated_png(event)
