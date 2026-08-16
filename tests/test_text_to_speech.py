"""Text-to-speech — the provider registry (resolve/availability) and the
text_to_speech tool (synthesizes via a backend, saves an audio file, returns a
MEDIA: tag, and is availability-gated). A fake backend stands in for a real TTS
API so nothing here hits the network.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.text_to_speech import TextToSpeechTool
from shipit_agent.tools.text_to_speech import providers as prov


class FakeTTS:
    def __init__(self, name="fake", available=True, fail=False):
        self.name = name
        self._available = available
        self._fail = fail
        self.calls = []

    def is_available(self):
        return self._available

    def synthesize(self, text, *, voice=None, **opts):
        self.calls.append((text, voice))
        if self._fail:
            raise RuntimeError("tts exploded")
        return b"ID3fake-audio-bytes", "mp3"


@pytest.fixture
def clean_registry():
    saved = dict(prov._REGISTRY)
    prov._REGISTRY.clear()
    yield
    prov._REGISTRY.clear()
    prov._REGISTRY.update(saved)


# ── registry ────────────────────────────────────────────────────────────────


def test_builtin_backends_registered_by_default():
    assert {"edge", "openai", "elevenlabs"} <= set(prov._REGISTRY)


def test_available_filters_by_readiness(clean_registry):
    prov.register_tts_provider(FakeTTS("ready", available=True))
    prov.register_tts_provider(FakeTTS("not", available=False))
    assert prov.available_providers() == ["ready"]


def test_build_single_available(clean_registry):
    p = prov.register_tts_provider(FakeTTS("only"))
    assert prov.build_tts_provider() is p


def test_build_explicit_wins(clean_registry):
    prov.register_tts_provider(FakeTTS("a"))
    b = prov.register_tts_provider(FakeTTS("b"))
    assert prov.build_tts_provider("b") is b


def test_build_prefers_edge_free_first(clean_registry):
    prov.register_tts_provider(FakeTTS("openai"))
    prov.register_tts_provider(FakeTTS("edge"))
    assert prov.build_tts_provider().name == "edge"


def test_build_unknown_raises(clean_registry):
    with pytest.raises(RuntimeError, match="Unknown TTS backend"):
        prov.build_tts_provider("nope")


def test_build_none_available_raises(clean_registry):
    with pytest.raises(RuntimeError, match="No text-to-speech backend"):
        prov.build_tts_provider()


# ── tool ──────────────────────────────────────────────────────────────────────


def _ctx():
    return ToolContext(prompt="")


def test_speaks_and_saves_with_media_tag(clean_registry, tmp_path):
    fake = prov.register_tts_provider(FakeTTS("fake"))
    out = TextToSpeechTool(output_dir=tmp_path).run(_ctx(), text="hello", voice="en-US-AriaNeural")
    assert out.metadata["ok"] is True and out.metadata["provider"] == "fake"
    assert out.metadata["format"] == "mp3" and out.metadata["bytes"] > 0
    assert f"MEDIA:{out.metadata['path']}" in out.text
    assert list(tmp_path.glob("speech-*.mp3"))
    assert fake.calls == [("hello", "en-US-AriaNeural")]


def test_requires_text(clean_registry, tmp_path):
    prov.register_tts_provider(FakeTTS("fake"))
    out = TextToSpeechTool(output_dir=tmp_path).run(_ctx(), text="  ")
    assert out.metadata["ok"] is False and "required" in out.text


def test_rejects_overlong_text(clean_registry, tmp_path):
    prov.register_tts_provider(FakeTTS("fake"))
    out = TextToSpeechTool(output_dir=tmp_path).run(_ctx(), text="x" * 9000)
    assert out.metadata["ok"] is False and "cap is" in out.text


def test_no_backend_is_a_clean_error(clean_registry, tmp_path):
    out = TextToSpeechTool(output_dir=tmp_path).run(_ctx(), text="hi")
    assert out.metadata["ok"] is False and "No text-to-speech backend" in out.text


def test_backend_failure_reported(clean_registry, tmp_path):
    prov.register_tts_provider(FakeTTS("fake", fail=True))
    out = TextToSpeechTool(output_dir=tmp_path).run(_ctx(), text="hi")
    assert out.metadata["ok"] is False and "exploded" in out.text


def test_tool_is_availability_gated(clean_registry):
    from shipit_agent.tools.availability import clear_cache, is_available

    tool = TextToSpeechTool()
    clear_cache()                              # drop any cached probe from earlier tests
    assert not is_available(tool)[0]           # no backend → gated out
    prov.register_tts_provider(FakeTTS("fake"))
    clear_cache()
    assert is_available(tool)[0] is True
