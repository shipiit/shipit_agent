"""Tests for the Anthropic "power passthrough" features added in v1.0.12:

* #10 interleaved thinking (beta header + thinking-block round-trip)
* #9  server-side context editing (``context_management`` param + beta)
* #8  citations (document blocks + citation parsing)
* endpoint routing: beta-only params/headers go to ``client.beta.messages``,
  and with every flag off the request is byte-identical to legacy and stays on
  the GA ``client.messages`` endpoint.

Request shapes are asserted through ``_build_request_kwargs`` where possible;
endpoint routing is asserted by monkeypatching a fake anthropic client that
exposes BOTH ``messages.create`` and ``beta.messages.create`` and records which
was hit and with what kwargs. Response parsing uses ``SimpleNamespace`` fakes.
"""
from __future__ import annotations

import sys
import types

from shipit_agent.llms import citations
from shipit_agent.llms.anthropic_adapter import (
    CONTEXT_MANAGEMENT_BETA,
    INTERLEAVED_THINKING_BETA,
    AnthropicChatLLM,
)
from shipit_agent.models import Message


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


# ----------------------------------------------------------------------
# Fake anthropic client capturing endpoint + kwargs
# ----------------------------------------------------------------------
class _Capture:
    def __init__(self, response):
        self.response = response
        self.ga_kwargs = None
        self.beta_kwargs = None

        capture = self

        class _GAMessages:
            def create(self, **kwargs):
                capture.ga_kwargs = kwargs
                return capture.response

        class _BetaMessages:
            def create(self, **kwargs):
                capture.beta_kwargs = kwargs
                return capture.response

        self._ga = _GAMessages()
        self._beta_messages = _BetaMessages()
        self.messages = self._ga
        self.beta = _ns(messages=self._beta_messages)


def _install_fake_anthropic(monkeypatch, response):
    fake = types.ModuleType("anthropic")
    captures = {}

    def _client(**_kwargs):
        cap = _Capture(response)
        captures["cap"] = cap
        return cap

    fake.Anthropic = _client
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return captures


_TEXT_RESPONSE = _ns(content=[_ns(type="text", text="ok")], usage=None)


# ======================================================================
# Endpoint routing / backward compatibility
# ======================================================================
class TestEndpointRouting:
    def test_flags_off_uses_ga_endpoint(self, monkeypatch) -> None:
        caps = _install_fake_anthropic(monkeypatch, _TEXT_RESPONSE)
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        llm.complete(messages=[Message(role="user", content="hi")], system_prompt="s")
        cap = caps["cap"]
        # Hit the GA endpoint, never the beta one.
        assert cap.ga_kwargs is not None
        assert cap.beta_kwargs is None
        # No power-feature keys leaked into the request.
        assert "betas" not in cap.ga_kwargs
        assert "context_management" not in cap.ga_kwargs

    def test_flags_off_no_extra_metadata(self, monkeypatch) -> None:
        _install_fake_anthropic(monkeypatch, _TEXT_RESPONSE)
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        out = llm.complete(messages=[Message(role="user", content="hi")])
        assert set(out.metadata) == {"model", "provider"}

    def test_context_management_routes_to_beta(self, monkeypatch) -> None:
        caps = _install_fake_anthropic(monkeypatch, _TEXT_RESPONSE)
        llm = AnthropicChatLLM(
            model="claude-sonnet-4",
            context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
        )
        llm.complete(messages=[Message(role="user", content="hi")])
        cap = caps["cap"]
        assert cap.ga_kwargs is None
        assert cap.beta_kwargs is not None
        assert CONTEXT_MANAGEMENT_BETA in cap.beta_kwargs["betas"]
        assert cap.beta_kwargs["context_management"] == {
            "edits": [{"type": "clear_tool_uses_20250919"}]
        }


# ======================================================================
# #10 Interleaved thinking
# ======================================================================
class TestInterleavedThinking:
    def test_beta_header_when_thinking_enabled(self) -> None:
        llm = AnthropicChatLLM(
            model="claude-sonnet-4",
            thinking_budget_tokens=1024,
            interleaved_thinking=True,
        )
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert INTERLEAVED_THINKING_BETA in kwargs["betas"]
        assert kwargs["thinking"]["type"] == "enabled"

    def test_no_beta_without_thinking_budget(self) -> None:
        # Interleaved flag on but thinking not enabled -> no beta (no-op).
        llm = AnthropicChatLLM(model="claude-sonnet-4", interleaved_thinking=True)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert "betas" not in kwargs

    def test_no_beta_when_flag_off(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", thinking_budget_tokens=1024)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert "betas" not in kwargs

    def test_thinking_blocks_round_tripped(self) -> None:
        llm = AnthropicChatLLM(
            model="claude-sonnet-4",
            thinking_budget_tokens=1024,
            interleaved_thinking=True,
        )
        msg = Message(
            role="assistant",
            content="answer",
            metadata={
                "tool_calls": [{"id": "t1", "name": "calc", "arguments": {}}],
                "thinking_blocks": [
                    {"type": "thinking", "thinking": "hmm", "signature": "sig123"}
                ],
            },
        )
        converted = llm._convert_messages([msg])
        blocks = converted[0]["content"]
        # Thinking block re-emitted FIRST, with its signature preserved.
        assert blocks[0]["type"] == "thinking"
        assert blocks[0]["signature"] == "sig123"
        assert any(b.get("type") == "tool_use" for b in blocks)

    def test_thinking_blocks_not_emitted_when_flag_off(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        msg = Message(
            role="assistant",
            content="answer",
            metadata={
                "tool_calls": [{"id": "t1", "name": "calc", "arguments": {}}],
                "thinking_blocks": [{"type": "thinking", "signature": "s"}],
            },
        )
        blocks = llm._convert_messages([msg])[0]["content"]
        assert all(b.get("type") != "thinking" for b in blocks)

    def test_thinking_blocks_captured_in_response_metadata(self, monkeypatch) -> None:
        response = _ns(
            content=[
                _ns(type="thinking", thinking="reasoning", signature="sigA"),
                _ns(type="text", text="done"),
            ],
            usage=None,
        )
        _install_fake_anthropic(monkeypatch, response)
        llm = AnthropicChatLLM(
            model="claude-sonnet-4",
            thinking_budget_tokens=1024,
            interleaved_thinking=True,
        )
        out = llm.complete(messages=[Message(role="user", content="hi")])
        assert out.metadata["thinking_blocks"][0]["signature"] == "sigA"
        assert out.reasoning_content == "reasoning"


# ======================================================================
# #9 Context management
# ======================================================================
class TestContextManagement:
    def test_param_and_beta_forwarded(self) -> None:
        cfg = {"edits": [{"type": "clear_tool_uses_20250919"}]}
        llm = AnthropicChatLLM(model="claude-sonnet-4", context_management=cfg)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert kwargs["context_management"] == cfg
        assert CONTEXT_MANAGEMENT_BETA in kwargs["betas"]

    def test_absent_when_unset(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert "context_management" not in kwargs


# ======================================================================
# #8 Citations
# ======================================================================
class TestCitations:
    def test_text_document_helper(self) -> None:
        doc = citations.text_document("source text", title="Doc")
        assert doc["type"] == "document"
        assert doc["source"] == {
            "type": "text",
            "media_type": "text/plain",
            "data": "source text",
        }
        assert doc["title"] == "Doc"
        assert doc["citations"] == {"enabled": True}

    def test_pdf_and_url_helpers(self) -> None:
        assert citations.pdf_document("YmFzZTY0")["source"]["type"] == "base64"
        assert citations.url_pdf_document("http://x/y.pdf")["source"] == {
            "type": "url",
            "url": "http://x/y.pdf",
        }

    def test_citations_can_be_disabled(self) -> None:
        doc = citations.text_document("x", citations=False)
        assert "citations" not in doc

    def test_documents_attached_to_last_user_message(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        doc = citations.text_document("grounding")
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="question?")],
            tools=None,
            system_prompt=None,
            documents=[doc],
        )
        content = kwargs["messages"][-1]["content"]
        assert isinstance(content, list)
        # Document prepended before the user's text.
        assert content[0]["type"] == "document"
        assert content[0]["citations"] == {"enabled": True}
        assert content[1] == {"type": "text", "text": "question?"}

    def test_no_documents_keeps_string_content(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert kwargs["messages"][-1]["content"] == "hi"

    def test_constructor_default_documents(self) -> None:
        doc = citations.text_document("ctx")
        llm = AnthropicChatLLM(
            model="claude-sonnet-4", prompt_caching=False, documents=[doc]
        )
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="q")],
            tools=None,
            system_prompt=None,
        )
        assert kwargs["messages"][-1]["content"][0]["type"] == "document"

    def test_citations_parsed_from_response(self, monkeypatch) -> None:
        citation = _ns(
            type="char_location",
            cited_text="the answer is 42",
            document_index=0,
            document_title="Doc",
            start_char_index=10,
            end_char_index=26,
        )
        response = _ns(
            content=[_ns(type="text", text="It is 42.", citations=[citation])],
            usage=None,
        )
        _install_fake_anthropic(monkeypatch, response)
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        out = llm.complete(messages=[Message(role="user", content="hi")])
        cites = out.metadata["citations"]
        assert len(cites) == 1
        assert cites[0]["cited_text"] == "the answer is 42"
        assert cites[0]["document_index"] == 0

    def test_no_citations_key_when_none(self, monkeypatch) -> None:
        response = _ns(content=[_ns(type="text", text="plain")], usage=None)
        _install_fake_anthropic(monkeypatch, response)
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        out = llm.complete(messages=[Message(role="user", content="hi")])
        assert "citations" not in out.metadata

    def test_extract_citations_handles_dict_blocks(self) -> None:
        blocks = [
            {"type": "text", "text": "x"},  # dict shape, no citations
        ]
        assert citations.extract_citations(blocks) == []
