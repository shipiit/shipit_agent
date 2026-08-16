"""Video generation — the provider registry (resolve/availability) and the
video_generate tool (blocks on a backend, saves an MP4, returns a MEDIA: tag,
and is availability-gated). A fake backend stands in for a real video API so
nothing here hits the network.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.video_generate import (
    FalVideoProvider,
    ReplicateVideoProvider,
    VideoGenerateTool,
)
from shipit_agent.tools.video_generate import providers as prov
from shipit_agent.tools.video_generate import validate_video_model


class FakeVideo:
    def __init__(self, name="fake", available=True, fail=False):
        self.name = name
        self._available = available
        self._fail = fail
        self.calls = []

    def is_available(self):
        return self._available

    def generate(self, prompt, *, duration=5, aspect_ratio="16:9", **opts):
        self.calls.append((prompt, duration, aspect_ratio))
        if self._fail:
            raise RuntimeError("render farm exploded")
        return b"\x00\x00\x00\x18ftypmp4fake", "mp4"


@pytest.fixture
def clean_registry():
    saved = dict(prov._REGISTRY)
    prov._REGISTRY.clear()
    yield
    prov._REGISTRY.clear()
    prov._REGISTRY.update(saved)


# ── registry ────────────────────────────────────────────────────────────────


def test_builtin_backends_registered_by_default():
    assert {"fal", "replicate"} <= set(prov._REGISTRY)


def test_available_filters_by_readiness(clean_registry):
    prov.register_video_provider(FakeVideo("ready", available=True))
    prov.register_video_provider(FakeVideo("not", available=False))
    assert prov.available_providers() == ["ready"]


def test_build_single_available(clean_registry):
    p = prov.register_video_provider(FakeVideo("only"))
    assert prov.build_video_provider() is p


def test_build_explicit_wins(clean_registry):
    prov.register_video_provider(FakeVideo("fal"))
    r = prov.register_video_provider(FakeVideo("replicate"))
    assert prov.build_video_provider("replicate") is r


def test_build_prefers_fal_first(clean_registry):
    prov.register_video_provider(FakeVideo("replicate"))
    prov.register_video_provider(FakeVideo("fal"))
    assert prov.build_video_provider().name == "fal"


def test_build_unknown_raises(clean_registry):
    with pytest.raises(RuntimeError, match="Unknown video backend"):
        prov.build_video_provider("nope")


def test_build_none_available_raises(clean_registry):
    with pytest.raises(RuntimeError, match="No video-generation backend"):
        prov.build_video_provider()


# ── tool ──────────────────────────────────────────────────────────────────────


def _ctx():
    return ToolContext(prompt="")


def test_generates_and_saves_with_media_tag(clean_registry, tmp_path):
    fake = prov.register_video_provider(FakeVideo("fake"))
    out = VideoGenerateTool(output_dir=tmp_path).run(
        _ctx(), prompt="a cat surfing", duration=8, aspect_ratio="9:16"
    )
    assert out.metadata["ok"] is True and out.metadata["provider"] == "fake"
    assert out.metadata["format"] == "mp4" and out.metadata["bytes"] > 0
    assert out.metadata["duration"] == 8 and out.metadata["aspect_ratio"] == "9:16"
    assert f"MEDIA:{out.metadata['path']}" in out.text
    assert list(tmp_path.glob("video-*.mp4"))
    assert fake.calls == [("a cat surfing", 8, "9:16")]


def test_requires_prompt(clean_registry, tmp_path):
    prov.register_video_provider(FakeVideo("fake"))
    out = VideoGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="  ")
    assert out.metadata["ok"] is False and "required" in out.text


def test_duration_is_clamped(clean_registry, tmp_path):
    fake = prov.register_video_provider(FakeVideo("fake"))
    out = VideoGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="hi", duration=999)
    assert out.metadata["duration"] == 30          # capped at _MAX_DURATION
    assert fake.calls[0][1] == 30


def test_bad_aspect_falls_back(clean_registry, tmp_path):
    prov.register_video_provider(FakeVideo("fake"))
    out = VideoGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="hi", aspect_ratio="banana")
    assert out.metadata["aspect_ratio"] == "16:9"


def test_no_backend_is_a_clean_error(clean_registry, tmp_path):
    out = VideoGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="hi")
    assert out.metadata["ok"] is False and "No video-generation backend" in out.text


def test_backend_failure_reported(clean_registry, tmp_path):
    prov.register_video_provider(FakeVideo("fake", fail=True))
    out = VideoGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="hi")
    assert out.metadata["ok"] is False and "exploded" in out.text


# ── model validation (permissive denylist) ───────────────────────────────────


def test_known_model_passes():
    validate_video_model("fal", "fal-ai/ltx-video", FalVideoProvider.known_models)  # no raise


def test_unknown_but_plausible_video_model_is_allowed():
    # A model we've never heard of is permitted — the backend has the final say.
    validate_video_model("fal", "fal-ai/brand-new-video-model-2027", FalVideoProvider.known_models)


@pytest.mark.parametrize(
    "chat_model",
    ["gpt-4o", "claude-opus-4-8", "gemini-2.0-flash", "dall-e-3", "llama-3.1-70b-instruct"],
)
def test_chat_or_image_model_is_rejected(chat_model):
    with pytest.raises(RuntimeError, match="not a text-to-video"):
        validate_video_model("fal", chat_model, FalVideoProvider.known_models)


def test_empty_model_is_rejected():
    with pytest.raises(RuntimeError, match="No fal video model"):
        validate_video_model("fal", "", FalVideoProvider.known_models)


def test_escape_hatch_disables_validation(monkeypatch):
    monkeypatch.setenv("SHIPIT_ALLOW_UNKNOWN_VIDEO_MODEL", "1")
    validate_video_model("fal", "gpt-4o", FalVideoProvider.known_models)  # bypassed → no raise


def test_replicate_has_its_own_known_models():
    assert ReplicateVideoProvider.known_models  # non-empty hint list


def test_tool_is_availability_gated(clean_registry):
    from shipit_agent.tools.availability import clear_cache, is_available

    tool = VideoGenerateTool()
    clear_cache()                              # drop any cached probe from earlier tests
    assert not is_available(tool)[0]           # no backend → gated out
    prov.register_video_provider(FakeVideo("fake"))
    clear_cache()
    assert is_available(tool)[0] is True
