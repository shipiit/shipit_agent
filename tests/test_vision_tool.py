"""Tests for :class:`shipit_agent.tools.vision.VisionTool`."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.vision import VisionTool


# ─────────────────────────── stub LLM ───────────────────────────


@dataclass
class _R:
    content: str = "A screenshot of a login form."
    usage: dict[str, int] = field(default_factory=dict)


class _StubVisionLLM:
    model = "stub-vision-1"

    def __init__(self, response: _R | None = None) -> None:
        self.calls: list[list[Any]] = []
        self.call_kwargs: list[dict[str, Any]] = []
        self._response = response or _R(
            content="A screenshot of a login form.",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    def complete(self, *, messages: list[Any], **kw: Any) -> _R:
        self.calls.append(messages)
        self.call_kwargs.append(kw)
        return self._response


# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(prompt="analyse this")


@pytest.fixture
def png_bytes() -> bytes:
    # A minimal but clearly-PNG-looking byte string.
    return b"\x89PNG\r\n\x1a\n" + b"fake-png-body"


@pytest.fixture
def png_file(tmp_path: Path, png_bytes: bytes) -> Path:
    p = tmp_path / "shot.png"
    p.write_bytes(png_bytes)
    return p


# ─────────────────────────── tool surface ───────────────────────────


class TestToolSurface:
    def test_name_and_description(self) -> None:
        tool = VisionTool()
        assert tool.name == "vision"
        assert "vision" in tool.description.lower()
        assert tool.prompt_instructions

    def test_schema_exposes_required_params(self) -> None:
        tool = VisionTool()
        props = tool.schema()["function"]["parameters"]["properties"]
        assert "image" in props
        assert "prompt" in props
        assert "detail" in props
        assert "max_tokens" in props
        assert tool.schema()["function"]["parameters"]["required"] == ["image"]
        assert props["detail"]["enum"] == ["low", "high", "auto"]


# ─────────────────────────── no-LLM guard ───────────────────────────


class TestNoLLM:
    def test_returns_no_llm_error(self, ctx: ToolContext) -> None:
        tool = VisionTool()
        out = tool.run(ctx, image="https://example.com/foo.png")
        assert out.metadata.get("error") == "no_llm"
        assert "LLM" in out.text or "llm" in out.text

    def test_falls_back_to_context_state_llm(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        ctx.state["llm"] = stub
        tool = VisionTool()  # no explicit llm
        out = tool.run(ctx, image="https://example.com/foo.png")
        assert out.metadata.get("error") is None
        assert len(stub.calls) == 1


# ─────────────────────────── image resolution ───────────────────────────


class TestImageResolution:
    def test_http_url_passthrough(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        url = "https://example.com/diagram.png"
        out = tool.run(ctx, image=url)
        assert out.metadata["image_url"] == url

    def test_local_png_becomes_base64_data_url(
        self, ctx: ToolContext, png_file: Path, png_bytes: bytes
    ) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        out = tool.run(ctx, image=str(png_file))
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")
        assert out.metadata["image_url"] == f"data:image/png;base64,{expected_b64}"

    @pytest.mark.parametrize(
        ("suffix", "expected_mime"),
        [
            (".png", "image/png"),
            (".jpg", "image/jpeg"),
            (".jpeg", "image/jpeg"),
            (".gif", "image/gif"),
            (".webp", "image/webp"),
        ],
    )
    def test_mime_type_detection(
        self,
        ctx: ToolContext,
        tmp_path: Path,
        suffix: str,
        expected_mime: str,
    ) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        p = tmp_path / f"image{suffix}"
        p.write_bytes(b"dummy-bytes")
        out = tool.run(ctx, image=str(p))
        assert out.metadata["image_url"].startswith(f"data:{expected_mime};base64,")

    def test_existing_data_url_passthrough(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        data_url = "data:image/png;base64,iVBORw0KGgo="
        out = tool.run(ctx, image=data_url)
        assert out.metadata["image_url"] == data_url

    def test_raw_base64_wrapped_as_data_url(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        raw_b64 = base64.b64encode(b"some-longer-fake-image-bytes-here").decode(
            "ascii"
        )
        out = tool.run(ctx, image=raw_b64)
        assert out.metadata["image_url"] == f"data:image/png;base64,{raw_b64}"

    def test_missing_file_returns_image_not_found(
        self, ctx: ToolContext, tmp_path: Path
    ) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        out = tool.run(ctx, image=str(tmp_path / "does-not-exist.png"))
        assert out.metadata.get("error") == "image_not_found"
        # Must not have called the LLM.
        assert stub.calls == []


# ─────────────────────────── happy-path wiring ───────────────────────────


class TestHappyPath:
    def test_message_role_and_content(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        tool.run(
            ctx,
            image="https://example.com/foo.png",
            prompt="Is there a Login button?",
        )
        messages = stub.calls[0]
        assert len(messages) == 1
        assert messages[0].role == "user"
        # Both the text prompt and the image URL reference are present.
        assert "Is there a Login button?" in messages[0].content
        assert "image_url" in messages[0].content
        # Structured parts are stashed in metadata for vision adapters.
        parts = messages[0].metadata["parts"]
        assert parts[0] == {"type": "text", "text": "Is there a Login button?"}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"] == "https://example.com/foo.png"

    def test_response_text_flows_back(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM(
            _R(content="I see a purple Login button.", usage={"total": 42})
        )
        tool = VisionTool(llm=stub)
        out = tool.run(ctx, image="https://example.com/foo.png")
        assert out.text == "I see a purple Login button."
        assert out.metadata["usage"] == {"total": 42}
        assert out.metadata["model"] == "stub-vision-1"
        assert out.metadata["provider"] == "vision"

    def test_default_prompt_used_when_missing(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        tool.run(ctx, image="https://example.com/foo.png")
        parts = stub.calls[0][0].metadata["parts"]
        assert parts[0]["text"] == "Describe this image in detail."


# ─────────────────────────── detail passthrough ───────────────────────────


class TestDetail:
    @pytest.mark.parametrize("detail", ["low", "high", "auto"])
    def test_detail_passes_through(self, ctx: ToolContext, detail: str) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        out = tool.run(
            ctx, image="https://example.com/foo.png", detail=detail
        )
        parts = stub.calls[0][0].metadata["parts"]
        assert parts[1]["image_url"]["detail"] == detail
        assert out.metadata["detail"] == detail

    def test_invalid_detail_falls_back_to_auto(self, ctx: ToolContext) -> None:
        stub = _StubVisionLLM()
        tool = VisionTool(llm=stub)
        out = tool.run(
            ctx, image="https://example.com/foo.png", detail="ultra-mega"
        )
        assert out.metadata["detail"] == "auto"
