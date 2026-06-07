"""Tests for Anthropic **server-side tool** constructor helpers and the
adapter's forwarding of them (v1.0.12 power passthrough, feature #4).

These cover the pure ``server_tools`` helpers (correct verified ``type`` /
``name`` strings, required beta headers) and the adapter's
``_build_request_kwargs`` behaviour: server tools forwarded verbatim (not
reshaped into client tools), client tools still translated, and the right
``betas`` attached only when a server tool requires one.
"""
from __future__ import annotations

import types

from shipit_agent.llms import server_tools as st
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.models import Message


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


CLIENT_TOOL = {
    "function": {
        "name": "calc",
        "description": "do math",
        "parameters": {"type": "object", "properties": {}},
    }
}


# ----------------------------------------------------------------------
# Constructor helpers
# ----------------------------------------------------------------------
class TestServerToolHelpers:
    def test_web_search_shape(self) -> None:
        t = st.web_search(max_uses=3)
        assert t["type"] == "web_search_20250305"
        assert t["name"] == "web_search"
        assert t["max_uses"] == 3

    def test_web_search_forwards_extra(self) -> None:
        t = st.web_search(allowed_domains=["example.com"])
        assert t["allowed_domains"] == ["example.com"]

    def test_code_execution_shape(self) -> None:
        t = st.code_execution()
        assert t == {"type": "code_execution_20250522", "name": "code_execution"}

    def test_computer_use_shape(self) -> None:
        t = st.computer_use(1024, 768, display_number=1)
        assert t["type"] == "computer_20250124"
        assert t["name"] == "computer"
        assert t["display_width_px"] == 1024
        assert t["display_height_px"] == 768
        assert t["display_number"] == 1

    def test_bash_shape(self) -> None:
        assert st.bash() == {"type": "bash_20250124", "name": "bash"}

    def test_text_editor_shape(self) -> None:
        t = st.text_editor()
        assert t["type"] == "text_editor_20250728"
        assert t["name"] == "str_replace_based_edit_tool"


# ----------------------------------------------------------------------
# is_server_tool / required_betas
# ----------------------------------------------------------------------
class TestBetaResolution:
    def test_is_server_tool(self) -> None:
        assert st.is_server_tool(st.web_search()) is True
        assert st.is_server_tool(CLIENT_TOOL) is False

    def test_web_search_needs_no_beta(self) -> None:
        # web_search is GA -> no beta header (keeps request on the GA endpoint).
        assert st.required_betas([st.web_search()]) == []

    def test_code_execution_beta(self) -> None:
        assert st.required_betas([st.code_execution()]) == [
            "code-execution-2025-05-22"
        ]

    def test_computer_use_beta(self) -> None:
        assert st.required_betas([st.computer_use(800, 600)]) == [
            "computer-use-2025-01-24"
        ]

    def test_betas_deduped_and_ordered(self) -> None:
        betas = st.required_betas(
            [st.code_execution(), st.computer_use(800, 600), st.code_execution()]
        )
        assert betas == ["code-execution-2025-05-22", "computer-use-2025-01-24"]

    def test_no_tools_no_betas(self) -> None:
        assert st.required_betas(None) == []
        assert st.required_betas([CLIENT_TOOL]) == []


# ----------------------------------------------------------------------
# Adapter forwarding via _build_request_kwargs
# ----------------------------------------------------------------------
class TestAdapterForwarding:
    def test_server_tool_forwarded_verbatim(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=[st.web_search(max_uses=2)],
            system_prompt=None,
        )
        tool = kwargs["tools"][0]
        # Forwarded with its ``type`` intact (NOT reshaped into a client tool).
        assert tool["type"] == "web_search_20250305"
        assert tool["name"] == "web_search"
        assert tool["max_uses"] == 2
        assert "input_schema" not in tool

    def test_mixed_client_and_server_tools(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=[CLIENT_TOOL, st.code_execution()],
            system_prompt=None,
        )
        client_t, server_t = kwargs["tools"]
        # Client tool translated to flat Anthropic shape.
        assert client_t["name"] == "calc"
        assert "input_schema" in client_t
        # Server tool passed through.
        assert server_t["type"] == "code_execution_20250522"
        # Code execution requires its beta header.
        assert "code-execution-2025-05-22" in kwargs["betas"]

    def test_web_search_no_beta_no_betas_key(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=[st.web_search()],
            system_prompt=None,
        )
        # GA tool -> no betas key -> stays on the GA endpoint.
        assert "betas" not in kwargs

    def test_default_caching_keeps_server_tool_wellformed(self) -> None:
        # Default config (prompt_caching=True) stamps a cache_control breakpoint
        # on the last tool. All five server-tool param types accept
        # cache_control (verified against the SDK), so the declaration stays
        # well-formed: its ``type``/``name`` survive and only cache_control is
        # added. This is the path real users hit: AnthropicChatLLM(model=...).
        llm = AnthropicChatLLM(model="claude-sonnet-4")  # prompt_caching defaults on
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=[st.web_search(max_uses=2)],
            system_prompt="sys",
        )
        tool = kwargs["tools"][-1]
        assert tool["type"] == "web_search_20250305"
        assert tool["name"] == "web_search"
        assert tool["max_uses"] == 2
        assert tool["cache_control"] == {"type": "ephemeral"}

    def test_does_not_mutate_caller_server_tool(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        tool = st.web_search()
        before = dict(tool)
        llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=[tool],
            system_prompt="sys",
        )
        assert tool == before


# ----------------------------------------------------------------------
# Response parsing: server_tool_use must not become a client ToolCall
# ----------------------------------------------------------------------
class TestServerToolResponseParsing:
    def _run(self, monkeypatch, content_blocks):
        import sys

        fake_anthropic = types.ModuleType("anthropic")
        response = _ns(content=content_blocks, usage=None)

        class _Messages:
            def create(self, **_kwargs):
                return response

        class _Client:
            def __init__(self, **_kwargs):
                self.messages = _Messages()

        fake_anthropic.Anthropic = _Client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        return llm.complete(messages=[Message(role="user", content="hi")])

    def test_server_tool_use_not_executed_locally(self, monkeypatch) -> None:
        out = self._run(
            monkeypatch,
            [
                _ns(type="text", text="Searching..."),
                _ns(
                    type="server_tool_use",
                    id="srvtoolu_1",
                    name="web_search",
                    input={"query": "weather"},
                ),
                _ns(
                    type="web_search_tool_result",
                    tool_use_id="srvtoolu_1",
                    content=[],
                ),
            ],
        )
        # NOT surfaced as a client tool call.
        assert out.tool_calls == []
        # Captured in metadata instead.
        assert out.metadata["server_tool_use"][0]["name"] == "web_search"
        assert out.metadata["server_tool_results"][0]["type"] == (
            "web_search_tool_result"
        )
        assert out.content == "Searching..."

    def test_no_server_metadata_when_absent(self, monkeypatch) -> None:
        out = self._run(monkeypatch, [_ns(type="text", text="hello")])
        assert "server_tool_use" not in out.metadata
        assert "server_tool_results" not in out.metadata
