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
