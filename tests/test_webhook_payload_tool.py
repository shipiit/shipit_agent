from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.webhook_payload import WebhookPayloadTool


def _ctx() -> ToolContext:
    return ToolContext(prompt="", metadata={}, state={})


def test_full_payload():
    tool = WebhookPayloadTool(payload={"event": "push", "repo": "shipit"})
    output = tool.run(_ctx())
    assert '"event": "push"' in output.text
    assert '"repo": "shipit"' in output.text


def test_nested_path():
    tool = WebhookPayloadTool(
        payload={"pull_request": {"title": "Fix bug", "number": 42}}
    )
    output = tool.run(_ctx(), path="pull_request.title")
    assert output.text == "Fix bug"


def test_numeric_index():
    tool = WebhookPayloadTool(payload={"items": ["a", "b", "c"]})
    output = tool.run(_ctx(), path="items.1")
    assert output.text == "b"


def test_missing_path():
    tool = WebhookPayloadTool(payload={"a": 1})
    output = tool.run(_ctx(), path="b.c.d")
    assert "not found" in output.text


def test_schema():
    tool = WebhookPayloadTool(payload={})
    schema = tool.schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "webhook_payload"
    assert fn["name"], "function name must be non-empty (Bedrock rejects empty)"
    assert fn["description"], "function description must be non-empty"
    assert "path" in fn["parameters"]["properties"]
