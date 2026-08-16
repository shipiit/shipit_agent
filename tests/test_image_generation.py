"""Image generation — the provider registry (resolve/availability) and the
image_generate tool (generates via a backend, returns the image inline via the
shared vision bridge, saves the full-res PNG, and is availability-gated).

A fake backend stands in for a real image API so nothing here hits the network.
"""

from __future__ import annotations

import base64

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.image_generate import ImageGenerateTool
from shipit_agent.tools.image_generate import providers as prov

# A 1x1 PNG — real bytes, tiny.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeProvider:
    def __init__(self, name="fake", available=True, fail=False):
        self.name = name
        self._available = available
        self._fail = fail
        self.calls = []

    def is_available(self):
        return self._available

    def generate(self, prompt, *, size="1024x1024", **opts):
        self.calls.append((prompt, size))
        if self._fail:
            raise RuntimeError("backend exploded")
        return _PNG


@pytest.fixture
def clean_registry(monkeypatch):
    """Isolate the registry so the built-in OpenAI backend doesn't interfere."""
    saved = dict(prov._REGISTRY)
    prov._REGISTRY.clear()
    yield
    prov._REGISTRY.clear()
    prov._REGISTRY.update(saved)


# ── the registry ───────────────────────────────────────────────────────────


def test_openai_backend_registered_by_default():
    assert "openai" in prov._REGISTRY


def test_available_providers_filters_by_key(clean_registry):
    prov.register_image_provider(FakeProvider("has_key", available=True))
    prov.register_image_provider(FakeProvider("no_key", available=False))
    assert prov.available_providers() == ["has_key"]


def test_build_resolves_single_available(clean_registry):
    p = prov.register_image_provider(FakeProvider("only"))
    assert prov.build_image_provider() is p


def test_build_explicit_name_wins(clean_registry):
    prov.register_image_provider(FakeProvider("a"))
    b = prov.register_image_provider(FakeProvider("b"))
    assert prov.build_image_provider("b") is b


def test_build_unknown_name_raises(clean_registry):
    with pytest.raises(RuntimeError, match="Unknown image backend"):
        prov.build_image_provider("nope")


def test_build_none_available_raises(clean_registry):
    with pytest.raises(RuntimeError, match="No image-generation backend"):
        prov.build_image_provider()


def test_build_prefers_preference_order(clean_registry):
    prov.register_image_provider(FakeProvider("fal"))
    prov.register_image_provider(FakeProvider("openai"))
    # openai wins over fal per _PREFERENCE.
    assert prov.build_image_provider().name == "openai"


def test_a_broken_availability_probe_reads_as_unavailable(clean_registry):
    class Boom:
        name = "boom"
        def is_available(self): raise RuntimeError("probe blew up")
        def generate(self, *a, **k): return _PNG
    prov.register_image_provider(Boom())
    assert prov.available_providers() == []


# ── the tool ─────────────────────────────────────────────────────────────────


def _ctx():
    return ToolContext(prompt="")


def test_generate_returns_the_image_inline(clean_registry, tmp_path):
    fake = prov.register_image_provider(FakeProvider("fake"))
    tool = ImageGenerateTool(output_dir=tmp_path)
    out = tool.run(_ctx(), prompt="a red circle", size="1024x1024")
    assert out.metadata["ok"] is True
    assert out.metadata["provider"] == "fake"
    # The image is fed back to the model via the shared vision bridge.
    assert out.metadata["image_base64"] and out.metadata["media_type"] == "image/png"
    assert out.metadata["vision"] is True
    # ...and saved full-res to disk.
    assert (tmp_path).glob("image-*.png")
    assert fake.calls == [("a red circle", "1024x1024")]


def test_generate_requires_a_prompt(clean_registry, tmp_path):
    prov.register_image_provider(FakeProvider("fake"))
    out = ImageGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="  ")
    assert out.metadata["ok"] is False and "required" in out.text


def test_generate_no_backend_is_a_clean_error(clean_registry, tmp_path):
    out = ImageGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="x")
    assert out.metadata["ok"] is False and "No image-generation backend" in out.text


def test_generate_backend_failure_is_reported(clean_registry, tmp_path):
    prov.register_image_provider(FakeProvider("fake", fail=True))
    out = ImageGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="x")
    assert out.metadata["ok"] is False and "exploded" in out.text


def test_bad_size_falls_back_to_square(clean_registry, tmp_path):
    fake = prov.register_image_provider(FakeProvider("fake"))
    ImageGenerateTool(output_dir=tmp_path).run(_ctx(), prompt="x", size="9999x1")
    assert fake.calls[0][1] == "1024x1024"


def test_tool_is_availability_gated(clean_registry):
    from shipit_agent.tools.availability import is_available

    tool = ImageGenerateTool()
    # no backend available → gated out
    ok, reason = is_available(tool)
    assert not ok
    # a backend appears → available
    prov.register_image_provider(FakeProvider("fake"))
    from shipit_agent.tools.availability import clear_cache
    clear_cache()
    assert is_available(tool)[0] is True
