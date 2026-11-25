import io
import json
from uuid import uuid4

import pytest
from PIL import Image

from backend.image_cli import ImageRequest, cancel, cancelled, generated_png, require_enabled
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


def test_cancellation_is_scoped_and_image_generation_requires_opt_in(monkeypatch):
    monkeypatch.delenv("AVS_ENABLE_CODEX_IMAGE", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        require_enabled()
    identifier = str(uuid4())
    cancel(identifier)
    assert cancelled(identifier)
    assert not cancelled(str(uuid4()))


def test_desktop_opt_in_uses_server_data_and_respects_explicit_environment(monkeypatch, tmp_path):
    marker = tmp_path / "enable-codex-image"
    marker.touch()
    monkeypatch.delenv("AVS_ENABLE_CODEX_IMAGE", raising=False)
    require_enabled()
    monkeypatch.setenv("AVS_ENABLE_CODEX_IMAGE", "0")
    with pytest.raises(ValueError, match="disabled"):
        require_enabled()
    marker.unlink()
    monkeypatch.setenv("AVS_ENABLE_CODEX_IMAGE", "1")
    require_enabled()


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
