"""Offline discovery benchmark; no provider calls or billed-token claims.

Run: PYTHONPATH=. .venv/bin/python scripts/benchmark_tool_discovery.py
Compares eager and automatic discovery across the same twenty tool operations.
Counts serialized request characters (messages, system prompt and schemas),
including the additional search step. This measures payload, not intelligence.
"""

from __future__ import annotations

import json

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class ReplayLLM:
    def __init__(self, target: str):
        self.target = target
        self.requests = 0
        self.request_chars = 0
        self.initial_tools = 0
        self.operations = 0

    def complete(self, *, messages, tools=None, system_prompt=None, **kwargs):
        self.requests += 1
        names = {(t.get("function") or {}).get("name") for t in tools or []}
        if self.requests == 1:
            self.initial_tools = len(names)
        self.request_chars += len(json.dumps({
            "system": system_prompt,
            "tools": tools,
            "messages": [{"role": m.role, "content": m.content,
                          "metadata": m.metadata} for m in messages],
        }, default=str))
        if self.operations == 20:
            return LLMResponse(content="Completed twenty lookups.")
        if self.target not in names:
            return LLMResponse(content="", tool_calls=[ToolCall(
                name="search_tools", arguments={"query": self.target},
            )])
        self.operations += 1
        return LLMResponse(content="", tool_calls=[ToolCall(
            name=self.target, arguments={"record_id": str(self.operations)},
        )])


def measure(size: int, deferred):
    calls = []

    def lookup(record_id: str):
        calls.append(record_id)
        return f"Record {record_id}: verified fixture result"

    tools = [FunctionTool.from_callable(
        lookup, name=f"archive_{i}_lookup",
        description=f"Read a record from archive {i}. Supply its record identifier.",
        read_only=True,
    ) for i in range(size)]
    llm = ReplayLLM(tools[-1].name)
    result = Agent(
        llm=llm, tools=tools, deferred_tools=deferred, max_iterations=25,
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
    ).run("Retrieve the twenty requested archive records.")
    assert len(calls) == 20
    assert not any(r.is_error for r in result.tool_results)
    return {"initial_tools": llm.initial_tools, "requests": llm.requests,
            "request_chars": llm.request_chars, "successful_operations": len(calls)}


if __name__ == "__main__":
    rows = []
    for size in (10, 30, 100, 500):
        eager, auto = measure(size, False), measure(size, "auto")
        rows.append({"catalog_size": size, "eager": eager, "auto": auto,
                     "request_payload_reduction_percent": round(
                         100 * (1 - auto["request_chars"] / eager["request_chars"]), 1)})
    print(json.dumps({"measurement": "offline serialized request characters", "results": rows}, indent=2))
