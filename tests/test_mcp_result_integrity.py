import json

import pytest

from shipit_agent.mcp import MCPError, MCPRemoteTool


class Transport:
    def __init__(self, result):
        self.result = result
    def request(self, method, params):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def tool(result, **kwargs):
    return MCPRemoteTool(server_name="fixture", name="lookup", description="Lookup",
                         transport=Transport(result), **kwargs)


@pytest.mark.parametrize("value", [{}, {"items": [{"id": "case-1", "amount": 42}]}])
def test_structured_only_result_is_visible_to_model(value):
    result = tool({"structuredContent": value}).run(None)
    assert json.loads(result.text) == value
    assert result.metadata["ok"] is True


def test_text_and_structured_content_are_not_duplicated():
    result = tool({"content": [{"type": "text", "text": "42"}],
                   "structuredContent": {"amount": 42}}).run(None)
    assert result.text == "42"
    assert result.metadata["structured_content"] == {"amount": 42}


@pytest.mark.parametrize("result", [MCPError("disconnected"), {"isError": True}])
def test_static_metadata_cannot_disguise_failed_execution(result):
    output = tool(result, metadata={"ok": True, "is_error": False, "error": "old", "server": "wrong"}).run(None)
    assert output.metadata["ok"] is False
    assert output.metadata["is_error"] is True
    assert output.metadata["server"] == "fixture"


def test_static_error_metadata_cannot_turn_success_into_failure():
    output = tool({"content": [{"type": "text", "text": "ok"}]},
                  metadata={"error": "stale", "is_error": True, "ok": False}).run(None)
    assert output.metadata["error"] is None
    assert output.metadata["is_error"] is False
    assert output.metadata["ok"] is True


@pytest.mark.parametrize("hint", [False, "false", "true", 1, None])
def test_read_only_hint_must_be_literal_true(hint):
    assert tool({}, annotations={"readOnlyHint": hint}).read_only is False
    assert tool({}, annotations={"readOnlyHint": True}).read_only is True
