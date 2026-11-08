"""Docs may only read attributes that AgentResult and AgentEvent really have.

test_docs_examples checks imports and keyword arguments; this catches the
other common slip, reading a field that doesn't exist (`result.steps`,
`event.step_number`), in any block that builds an Agent.
"""

from __future__ import annotations

import dataclasses
import re

from shipit_agent.core.models.results import AgentEvent, AgentResult
from tests.test_docs_examples import DOCS, _nav_pages

_FENCE = re.compile(r"^(`{3,})(?:python|py)\b.*?\n(.*?)^\1\s*$", re.M | re.S)
_AGENT = re.compile(r"^\s*(\w+)\s*=\s*Agent(?:\.with_builtins)?\(", re.M)


def _names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)} | {n for n in dir(cls) if not n.startswith("_")}


_RESULT = _names(AgentResult)
_EVENT = _names(AgentEvent)


def _unknown_attributes(code: str) -> list[str]:
    unknown: list[str] = []
    for agent in set(_AGENT.findall(code)):
        # `x = agent.run(...)` exactly; `agent.run(...).parsed` is another type.
        results = re.findall(rf"^\s*(\w+)\s*=\s*(?:await\s+)?{agent}\.a?run\([^\n]*\)\s*$", code, re.M)
        events = re.findall(rf"\bfor\s+(\w+)\s+in\s+{agent}\.a?stream\(", code)
        for names, known in ((results, _RESULT), (events, _EVENT)):
            for name in set(names):
                unknown += [f"{name}.{a}" for a in re.findall(rf"\b{name}\.(\w+)", code) if a not in known]
    return sorted(set(unknown))


def test_unknown_attribute_detection() -> None:
    code = (
        "agent = Agent(llm=llm)\n"
        "result = agent.run('x')\n"
        "print(result.output, result.step_count)\n"
        "for event in agent.stream('x'):\n"
        "    print(event.type, event.step_number)\n"
        "parsed = agent.run('x').parsed\n"
        "print(parsed.anything)\n"
    )
    assert _unknown_attributes(code) == ["event.step_number", "result.step_count"]


def test_docs_read_only_real_result_and_event_attributes() -> None:
    problems = []
    for page in _nav_pages():
        for match in _FENCE.finditer((DOCS / page).read_text(encoding="utf-8")):
            code = match.group(2)
            if code.startswith("# docs: no-check"):
                continue
            problems += [f"{page}: {attr}" for attr in _unknown_attributes(code)]
    assert not problems, "attributes that don't exist:\n" + "\n".join(problems)
