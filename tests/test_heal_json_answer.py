"""A JSON *answer* must never be promoted to a call of a no-argument tool.

Found live: asked for "my details as JSON", the model wrote the JSON object as
its answer. Nameless-object healing matched it to ``list_documents`` — the one
tool whose schema declares no properties, which the key check skipped — and
removed it from the answer. The run then had an empty answer, a phantom tool
call and a duplicate-call loop.
"""

from __future__ import annotations

from shipit_agent.tool_healing import heal_tool_calls

ANSWER = '```json\n{"name": "Asha", "product": "Lumen", "city": "Lisbon", "budget_eur": 50000}\n```'
SCHEMAS = {
    "list_documents": {"type": "object", "properties": {}, "required": []},
    "web_search": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}


def test_a_json_answer_is_left_as_the_answer():
    text, calls = heal_tool_calls(ANSWER, set(SCHEMAS), schemas=SCHEMAS)
    assert calls == [] and text == ANSWER


def test_a_bare_object_still_heals_to_the_tool_whose_keys_it_uses():
    text, calls = heal_tool_calls('{"query": "lisbon time zone"}', set(SCHEMAS), schemas=SCHEMAS)
    assert [c.name for c in calls] == ["web_search"]


def test_a_named_call_to_a_no_argument_tool_still_heals():
    raw = '{"name": "list_documents", "arguments": {}}'
    _, calls = heal_tool_calls(raw, set(SCHEMAS), schemas=SCHEMAS)
    assert [c.name for c in calls] == ["list_documents"]


FILE_SCHEMAS = {
    "write_file": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                   "required": ["path", "content"]},
    "read_file": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    "present_file": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
}


def test_the_one_tool_that_declares_every_key_wins_a_tie():
    """Found live: a text <tool_call> {"path", "content"} fit write_file,
    read_file and present_file (all declare path), so it was dropped as
    ambiguous and the file was never written."""
    text = ('I will create the file.\n<tool_call>\n{"path": "notes.md", "content": "# Notes"}\n'
            '</tool_call>')
    _, calls = heal_tool_calls(text, set(FILE_SCHEMAS), schemas=FILE_SCHEMAS)
    assert [(c.name, c.arguments) for c in calls] == [("write_file", {"path": "notes.md", "content": "# Notes"})]


def test_a_real_tie_is_still_left_alone():
    text = '<tool_call>\n{"path": "notes.md"}\n</tool_call>'
    _, calls = heal_tool_calls(text, {"read_file", "present_file"}, schemas=FILE_SCHEMAS)
    assert calls == []
