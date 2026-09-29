"""Opt-in billed Gemma evaluation of safe MCP/skill/failure fixture scenarios.

No production records, mutations or credential logging. Exact checks measure
these fixtures only, not general intelligence. Reports include failed trials.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from shipit_agent import Agent, FunctionTool, Skill, SkillRegistry
from shipit_agent.llms.factory import load_env_file
from shipit_agent.llms.openai_adapter import BedrockGemmaChatLLM
from shipit_agent.llms.bedrock_token import bedrock_bearer_token
from shipit_agent.tools.base import ToolOutput
from evaluate_agent_session import build_tools


def evaluate(llm, *, max_task_tokens=None):
    tools, mcps = build_tools(stdio=True)
    skill = Skill(id="evidence-review", name="Evidence review",
                  description="Format an evidence assessment with uncertainty.",
                  prompt_template="Write two headings: Evidence and Unknowns. Cite exact retrieved values. "
                       "Do not guess missing records or treat tool failure as an empty result.")
    registry = SkillRegistry()
    registry.register(skill)
    failed_calls = []

    def unavailable(query: str):
        failed_calls.append(query)
        return ToolOutput(text="Fixture archive unavailable: connection refused. No records retrieved.",
                          metadata={"is_error": True})

    tools.extend([FunctionTool.from_callable(unavailable, name="offline_archive",
                  description="Search the offline archive. Reports a connection error if unavailable.", read_only=True)])
    scenarios = [
        ("no_tools", "What is 6 times 7? Answer with the number only.", ["42"], True),
        ("discover_mcp", "Use the case archive to retrieve CASE-1 and give its evidence code and amount.", ["evidence-15838", "117"], False),
        ("reuse_history", "Without tools, what is twice the amount you just retrieved?", ["234"], True),
        ("load_skill", "Load the evidence-review skill, then assess the retrieved case using its format. Do not retrieve the case again.", ["Evidence", "Unknowns", "evidence-15838"], False),
        ("missing_record", "Look up CASE-99 in the case archive. If missing, say NOT_FOUND; do not guess.", ["NOT_FOUND"], False),
        ("missing_not_forgotten", "Without another lookup, repeat CASE-1's evidence code.", ["evidence-15838"], True),
        ("tool_error", "Query offline_archive for CASE-1 once. If it fails, say UNAVAILABLE, not NOT_FOUND.", ["UNAVAILABLE"], False),
        ("error_recall", "Without tools, was the last source empty or unavailable? Say UNAVAILABLE for a connection failure.", ["UNAVAILABLE"], True),
        ("cross_source", "Retrieve CASE-4 from the working case archive, then give CASE-1 and CASE-4 evidence codes.", ["evidence-15838", "evidence-39595"], False),
        ("final_recall", "Without tools, sum the amounts of CASE-1 and CASE-4 from this conversation.", ["285"], True),
    ]
    totals = Counter()
    passed = 0
    with Agent(llm=llm, tools=tools, mcps=mcps, max_iterations=7,
               max_task_tokens=max_task_tokens,
               auto_use_skills=False, auto_project_memory=False, auto_project_skills=False,
               skill_source=None, skill_registry=registry, progressive_skills=True,
               prompt="Use evidence from tools and the conversation. Be concise and distinguish errors from empty results.") as agent:
        for name, prompt, expected, no_tools in scenarios:
            start = time.monotonic()
            calls = []
            answer = ""
            summary = {}
            for event in agent.stream(prompt):
                if event.type == "tool_called":
                    calls.append(event.payload)
                elif event.type == "final_answer":
                    answer = event.payload.get("content", "")
                elif event.type == "run_summary":
                    summary = event.payload
            ok = all(value in answer for value in expected) and (not no_tools or not calls)
            if name == "tool_error":
                ok = ok and len(failed_calls) == 1
            passed += int(ok)
            totals.update(summary.get("usage", {}))
            yield {"scenario": name, "passed": ok, "answer": answer,
                   "tool_calls": calls, "elapsed_seconds": round(time.monotonic()-start, 3),
                   "summary": summary}
    yield {"evaluation": "live Gemma; synthetic data; stdio MCP; no production tools",
           "passed": passed, "scenarios": len(scenarios), "usage": dict(totals)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", required=True)
    parser.add_argument("--max-task-tokens", type=int, default=None,
                        help="Optional soft per-turn token budget")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to authorize billed provider calls")
    load_env_file()
    llm = BedrockGemmaChatLLM(model="google.gemma-4-31b",
                            api_key=bedrock_bearer_token(required=True), max_tokens=1024)
    with open(args.report, "x") as report:
        for row in evaluate(llm, max_task_tokens=args.max_task_tokens):
            line = json.dumps(row, default=str)
            report.write(line + "\n")
            report.flush()
            print(line, flush=True)
