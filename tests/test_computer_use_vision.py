"""Tests for the vision-feedback path on computer_use screenshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.computer_use import ComputerUseTool


class _FakeBackend:
    """Writes a fixed byte string as the "PNG" so we can assert on b64."""

    def __init__(self, payload: bytes = b"\x89PNG\r\n\x1a\n-fake-png-bytes-") -> None:
        self.platform = "test"
        self.payload = payload

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.payload)
        return path

    # Methods the tool may delegate to but aren't needed for these tests.
    def click(self, *a: Any, **kw: Any) -> None:
        pass

    def move(self, *a: Any, **kw: Any) -> None:
        pass


@pytest.fixture
def fake_backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(
        "shipit_agent.tools.computer_use.computer_use_tool.resolve_backend",
        lambda: fake,
    )
    return fake


@pytest.fixture
def tool(tmp_path: Path) -> ComputerUseTool:
    return ComputerUseTool(output_dir=tmp_path)


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(prompt="demo")


# ─────────────────────── default behaviour ───────────────────────


class TestVisionDefault:
    def test_screenshot_includes_base64_by_default(
        self,
        tool: ComputerUseTool,
        fake_backend: _FakeBackend,
        ctx: ToolContext,
    ) -> None:
        out = tool.run(ctx, action="screenshot")
        assert out.metadata["ok"] is True
        assert out.metadata.get("vision") is True
        assert out.metadata["media_type"] == "image/png"
        # Base64 of the raw payload.
        import base64

        expected = base64.b64encode(fake_backend.payload).decode("ascii")
        assert out.metadata["image_base64"] == expected

    def test_text_still_reports_saved_path(
        self,
        tool: ComputerUseTool,
        fake_backend: _FakeBackend,
        ctx: ToolContext,
    ) -> None:
        out = tool.run(ctx, action="screenshot")
        assert out.text.startswith("Screenshot saved: ")
        assert Path(out.metadata["path"]).exists()


# ─────────────────────── opt-outs + guardrails ───────────────────────


class TestVisionOptOut:
    def test_vision_false_omits_base64(
        self,
        tool: ComputerUseTool,
        fake_backend: _FakeBackend,
        ctx: ToolContext,
    ) -> None:
        out = tool.run(ctx, action="screenshot", vision=False)
        assert "image_base64" not in out.metadata
        assert out.metadata.get("vision") is not True


class TestSizeCap:
    def test_refuses_to_embed_giant_png(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ctx: ToolContext,
    ) -> None:
        # 5 MB — over the 4 MB cap.
        big = b"\x89PNG" + b"x" * (5 * 1024 * 1024)
        monkeypatch.setattr(
            "shipit_agent.tools.computer_use.computer_use_tool.resolve_backend",
            lambda: _FakeBackend(payload=big),
        )
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(ctx, action="screenshot")
        assert out.metadata.get("vision") is False
        assert "too large" in out.metadata.get("vision_skip_reason", "")
        assert "image_base64" not in out.metadata


# ─────────────────────── schema ───────────────────────


class TestSchema:
    def test_vision_flag_is_in_schema(self, tool: ComputerUseTool) -> None:
        props = tool.schema()["function"]["parameters"]["properties"]
        assert "vision" in props
        assert props["vision"]["default"] is True
