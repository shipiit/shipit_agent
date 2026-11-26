"""What an SDK ``@tool`` may return and how its schema may be written."""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, Required, TypedDict

import pytest

from shipit_agent.sdk import ToolAnnotations, create_sdk_mcp_server, tool
from shipit_agent.sdk.tools import json_schema

PNG = "aGVsbG8="


def _run(handler: Any, schema: Any = None, **arguments: Any) -> Any:
    made = tool("t", "A tool", schema or {"x": str})(handler)
    server = create_sdk_mcp_server("s", tools=[made])["instance"]
    return server.discover_tools()[0].handler(None, **arguments)


def test_an_image_block_reaches_the_model_as_an_image() -> None:
    out = _run(lambda args: {"content": [{"type": "text", "text": "chart"}, {"type": "image", "data": PNG, "mimeType": "image/jpeg"}]})
    assert out.text == "chart"
    assert (out.metadata["image_base64"], out.metadata["media_type"], out.metadata["vision"]) == (PNG, "image/jpeg", True)


def test_an_image_of_a_type_models_cannot_see_is_described_in_words() -> None:
    out = _run(lambda args: {"content": [{"type": "image", "data": PNG, "mimeType": "image/tiff"}]})
    assert "image_base64" not in out.metadata
    assert out.text == "[image/tiff image not shown]"


def test_resources_and_links_are_given_as_text() -> None:
    out = _run(
        lambda args: {
            "content": [
                {"type": "resource", "resource": {"uri": "file:///r.md", "text": "# Report"}},
                {"type": "resource", "resource": {"uri": "file:///r.bin", "blob": "AAAA"}},
                {"type": "resource_link", "uri": "https://x.dev/a", "name": "A", "description": "the A page"},
            ]
        }
    )
    assert out.text == "[file:///r.md]\n# Report\n[file:///r.bin: binary content not shown]\nA (https://x.dev/a): the A page"


def test_structured_content_and_the_blocks_are_kept_for_callers() -> None:
    blocks = [{"type": "text", "text": "ok"}]
    out = _run(lambda args: {"content": blocks, "structuredContent": {"n": 1}})
    assert out.metadata["structured_content"] == {"n": 1} and out.metadata["content_blocks"] == blocks


@pytest.mark.parametrize("flag", ["is_error", "isError"])
def test_either_spelling_marks_an_error_and_keeps_the_image(flag: str) -> None:
    out = _run(lambda args: {"content": [{"type": "text", "text": "bad"}, {"type": "image", "data": PNG, "mimeType": "image/png"}], flag: True})
    assert out.metadata["is_error"] is True and out.metadata["image_base64"] == PNG


@pytest.mark.parametrize("result", [None, "plain", {"content": None}, {"content": ["odd", 3]}, {}])
def test_odd_results_do_not_fail(result: Any) -> None:
    out = _run(lambda args: result)
    assert out.text == ("plain" if result == "plain" else "None" if result is None else "")


def test_annotated_types_give_descriptions() -> None:
    schema = json_schema({"lat": Annotated[float, "Latitude"], "tags": list[str], "n": int, "odd": object})
    assert schema["properties"] == {
        "lat": {"type": "number", "description": "Latitude"},
        "tags": {"type": "array"},
        "n": {"type": "integer"},
        "odd": {"type": "string"},
    }
    assert schema["required"] == ["lat", "tags", "n", "odd"]


def test_a_typed_dict_leaves_not_required_keys_optional() -> None:
    class Search(TypedDict):
        query: Annotated[str, "What to find"]
        limit: NotRequired[int]

    schema = json_schema(Search)
    assert schema["properties"] == {"query": {"type": "string", "description": "What to find"}, "limit": {"type": "integer"}}
    assert schema["required"] == ["query"]


def test_a_full_json_schema_passes_through_and_an_empty_one_takes_no_arguments() -> None:
    full = {"type": "object", "properties": {"a": {"type": "string", "enum": ["x"]}}, "required": []}
    assert json_schema(full) == full
    assert json_schema({}) == {"type": "object", "properties": {}, "required": []}


def test_annotations_as_an_object_or_a_dict_mark_a_tool_read_only() -> None:
    for given in (ToolAnnotations(readOnlyHint=True), {"readOnlyHint": True}, {"read_only_hint": True}):
        made = tool("t", "A tool", {"x": str}, annotations=given)(lambda args: {})
        assert create_sdk_mcp_server("s", tools=[made])["instance"].discover_tools()[0].read_only is True
    plain = tool("t", "A tool", {"x": str})(lambda args: {})
    assert create_sdk_mcp_server("s", tools=[plain])["instance"].discover_tools()[0].read_only is False


def test_a_partial_typed_dict_requires_only_what_is_marked_required() -> None:
    class Patch(TypedDict, total=False):
        id: Required[str]
        title: str

    assert json_schema(Patch)["required"] == ["id"]


def test_a_schema_or_annotations_of_the_wrong_kind_are_refused() -> None:
    with pytest.raises(TypeError, match="input_schema"):
        json_schema(["x"])
    with pytest.raises(TypeError, match="annotations"):
        tool("t", "A tool", {"x": str}, annotations="read-only")(lambda args: {})


def test_in_a_run_the_model_is_shown_the_image_the_tool_returned() -> None:
    import asyncio

    from shipit_agent.core.models import ToolCall
    from shipit_agent.llms.base import LLMResponse
    from shipit_agent.sdk import AgentOptions, query

    seen: list[list[Any]] = []

    class _Looks:
        model = "claude-sonnet-5-5"

        def complete(self, *, messages: list[Any], **_: Any) -> LLMResponse:
            seen.append(list(messages))
            if len(seen) == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(name="charts__draw", arguments={"x": "a"}, id="c1")])
            return LLMResponse(content="A chart.")

    draw = tool("draw", "Draw a chart", {"x": str})(
        lambda args: {"content": [{"type": "text", "text": "drawn"}, {"type": "image", "data": PNG, "mimeType": "image/png"}]}
    )
    options = AgentOptions(
        llm=_Looks(), tools=[], mcp_servers={"charts": create_sdk_mcp_server("charts", tools=[draw])},
        allowed_tools=["mcp__charts__draw"],
    )

    async def run() -> None:
        async for _ in query(prompt="draw", options=options):
            pass

    asyncio.run(run())
    images = [
        block
        for message in seen[1]
        if isinstance(message.content, list)
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "image"
    ]
    assert [image["source"]["data"] for image in images] == [PNG]
