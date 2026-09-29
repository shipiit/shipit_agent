"""Opt-in real-model, multi-user-turn evaluation with safe fixture tools.

No production records or external tool mutations. Provider calls are billed.
Outputs per-turn JSONL metrics, never credentials. Evidence checks are exact
fixture checks, not a general quality or intelligence score.

PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py \
    --live --provider bedrock --model google.gemma-4-31b --turns 20
"""
from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path
from collections import Counter

from shipit_agent import Agent, FunctionTool, MCPServer, MCPTool
from shipit_agent.deferral import DiscoveryPolicy
from shipit_agent.policies import RetryPolicy
from shipit_agent.tools.base import ToolOutput


RECORDS = [{"id": f"CASE-{i}", "code": f"evidence-{7919 * (i + 1)}",
            "amount": 100 + i * 17, "body": "Fixture background. " * 1000}
           for i in range(5)]


def lookup(record_id: str) -> ToolOutput:
    rows = [r for r in RECORDS if r["id"] == record_id]
    return ToolOutput.from_records(rows, fields=["id", "code", "amount"], source="evaluation fixture")


def scenarios():
    for i, row in enumerate(RECORDS):
        yield f"Use the case archive to retrieve {row['id']}. Return its exact evidence code and amount.", [row["code"], str(row["amount"])]
        yield "Without another lookup, repeat the evidence code of the case just retrieved.", [row["code"]]
        yield "What is twice that case's amount? Use the amount previously retrieved.", [str(row["amount"] * 2)]
        yield "Repeat the first case's evidence code and the most recent case's code. Do not guess.", [RECORDS[0]["code"], row["code"]]


def build_tools(*, stdio=False):
    def unrelated(query: str):
        return "This fixture contains no case records."
    tools = [FunctionTool.from_callable(unrelated, name=f"utility_{i}",
             description=f"Utility {i} for unrelated fixture diagnostics.", read_only=True)
             for i in range(20)]
    mcp = MCPServer(name="case_archive").register_many([MCPTool(
        name="archive_case_lookup", description="Retrieve a case archive record with evidence code and amount by case ID.",
        input_schema={"type": "object", "properties": {"record_id": {"type": "string"}}, "required": ["record_id"]},
        handler=lambda context, record_id: lookup(record_id), read_only=True,
    )])
    if stdio:
        from shipit_agent.mcp import RemoteMCPServer, PersistentMCPSubprocessTransport
        mcp = RemoteMCPServer(name="case_archive", transport=PersistentMCPSubprocessTransport(
            [sys.executable, str(Path(__file__).with_name("fixture_mcp_server.py"))], timeout=5))
    return tools, [mcp]


def evaluate(llm, *, turns=20, eager=False, context_window=0, stdio=False):
    tools, mcps = build_tools(stdio=stdio)
    agent = Agent(llm=llm, tools=tools, mcps=mcps,
        deferred_tools=False if eager else DiscoveryPolicy(), max_iterations=6,
        context_window_tokens=context_window,
        prompt="Answer from the supplied fixture tools and conversation. Never invent evidence. Keep answers concise.",
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        retry_policy=RetryPolicy(max_llm_retries=0, request_timeout=60))
    totals = Counter()
    event_totals = Counter()
    passed = 0
    workload = list(scenarios())
    for turn in range(1, turns + 1):
        prompt, expected = workload[(turn - 1) % len(workload)]
        started = time.monotonic()
        first_delta = None
        counts = Counter()
        answer = ""
        summary = {}
        for event in agent.stream(prompt):
            counts[event.type] += 1
            if event.type == "text_delta" and first_delta is None:
                first_delta = time.monotonic() - started
            if event.type == "final_answer":
                answer = event.payload.get("content", "")
            if event.type == "run_summary":
                summary = event.payload
        checks = all(value in answer for value in expected)
        passed += int(checks)
        totals.update(summary.get("usage", {}))
        event_totals.update(counts)
        yield {"turn": turn, "prompt": prompt, "answer": answer,
               "evidence_check_passed": checks, "elapsed_seconds": round(time.monotonic() - started, 3),
               "first_delta_seconds": first_delta, "events": dict(counts), "summary": summary}
    yield {"evaluation": "live provider, safe fixture tools; no production data",
           "mcp_transport": "stdio subprocess" if stdio else "in-process",
           "turns": turns, "passed_evidence_checks": passed, "usage": dict(totals),
           "events": dict(event_totals), "context_window": context_window}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow billed provider calls")
    parser.add_argument("--provider", choices=["bedrock", "litellm"], default="bedrock")
    parser.add_argument("--model", required=True)
    parser.add_argument("--turns", type=int, choices=range(1, 61), default=20)
    parser.add_argument("--eager", action="store_true")
    parser.add_argument("--context-window", type=int, default=0,
                        help="Smaller input budget to exercise real compaction; 0 uses model defaults")
    parser.add_argument("--mcp-stdio", action="store_true")
    parser.add_argument("--report", type=Path, help="Create a new JSONL report; existing files are never overwritten")
    parser.add_argument("--trace-fixture-requests", action="store_true",
                        help="Include synthetic model-request messages in the report for history debugging")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize real provider requests")
    from shipit_agent.llms.factory import load_env_file
    load_env_file()
    if args.provider == "bedrock":
        from shipit_agent.llms.openai_adapter import BedrockGemmaChatLLM
        from shipit_agent.llms.bedrock_token import bedrock_bearer_token
        llm = BedrockGemmaChatLLM(model=args.model, api_key=bedrock_bearer_token(required=True), max_tokens=1024)
    else:
        from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM
        llm = LiteLLMChatLLM(model=args.model, max_tokens=1024)
    report = args.report.open("x") if args.report else None
    requests = []
    if args.trace_fixture_requests:
        from dataclasses import asdict
        from functools import wraps
        complete = llm.complete

        @wraps(complete)
        def traced_complete(*a, **kw):
            requests.append([asdict(message) for message in kw.get("messages", [])])
            return complete(*a, **kw)

        llm.complete = traced_complete
    try:
        for row in evaluate(llm, turns=args.turns, eager=args.eager, context_window=args.context_window, stdio=args.mcp_stdio):
            line = json.dumps(row, default=str)
            print(line, flush=True)
            if report:
                if args.trace_fixture_requests:
                    row["fixture_requests"] = list(requests)
                    line = json.dumps(row, default=str)
                report.write(line + "\n")
                report.flush()
            requests.clear()
    finally:
        if report:
            report.close()


if __name__ == "__main__":
    main()
