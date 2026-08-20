"""Deep live streaming harness — Gemma 4 on AWS Bedrock Mantle.

Many local tools + a linked MCP server + an `ask_user` interactive tool,
driven through `agent.stream()`, recording EVERY AgentEvent (type, message,
payload keys, timestamp) to a JSONL log and printing a live transcript.

This is a manual harness, not a CI test — it costs money and needs AWS
credentials plus the bedrock-mantle provider checkout. Run:

    python tests/live/live_streaming_gemma.py

Env:
    SHIPIT_MANTLE_PROVIDER   path to bedrock_mantle_provider.py (has a default)
    SHIPIT_AUDIT_MODEL       model id (default bedrock-mantle/google.gemma-4-26b-a4b)
    SHIPIT_STREAM_LOG        output JSONL path (default ./gemma_stream_events.jsonl)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from shipit_agent import MCPServer, MCPTool
from shipit_agent.agent import Agent
from shipit_agent.policies import RetryPolicy
from shipit_agent.tools.ask_user.ask_user_tool import AskUserTool
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool

PROVIDER = os.getenv(
    "SHIPIT_MANTLE_PROVIDER",
    "/Users/rahulraj/Documents/MYWORK/AFTDRK/CACHE/DRK_CACHE_BACK"
    "/drk_cache/llm/bedrock_mantle_provider.py",
)
MODEL = os.getenv("SHIPIT_AUDIT_MODEL", "bedrock-mantle/google.gemma-4-26b-a4b")
LOG_PATH = os.getenv("SHIPIT_STREAM_LOG", "./gemma_stream_events.jsonl")


# ── local tool fleet ─────────────────────────────────────────────────────


class SimpleTool:
    def __init__(self, name, description, params, required, fn, read_only=True):
        self.name = name
        self.description = description
        self._params = params
        self._required = required
        self._fn = fn
        self.read_only = read_only

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self._params,
                    "required": self._required,
                },
            },
        }

    def run(self, context, **kwargs):
        return ToolOutput(text=self._fn(**kwargs), metadata={})


def build_tools():
    orders = [
        {"id": "A-1", "customer": "ACME", "value_eur": 750, "status": "open"},
        {"id": "A-2", "customer": "ACME", "value_eur": 1200, "status": "open"},
        {"id": "B-1", "customer": "Globex", "value_eur": 90, "status": "open"},
    ]
    return [
        ToolSearchTool(),
        AskUserTool(),
        SimpleTool("weather_lookup", "Current weather for a city.",
                   {"city": {"type": "string"}}, ["city"],
                   lambda city, **_: f"Weather in {city}: 21°C, clear."),
        SimpleTool("calculator", "Evaluate arithmetic.",
                   {"expression": {"type": "string"}}, ["expression"],
                   lambda expression, **_: str(
                       eval(expression, {"__builtins__": {}}, {})  # noqa: S307
                       if set(expression) <= set("0123456789+-*/(). ")
                       else "error")),
        SimpleTool("orders_db_query", "Query open orders by min value.",
                   {"min_value_eur": {"type": "number"}}, [],
                   lambda min_value_eur=0, **_: json.dumps(
                       [o for o in orders if o["value_eur"] >= float(min_value_eur or 0)])),
        SimpleTool("currency_convert", "Convert EUR to USD.",
                   {"amount": {"type": "number"}}, ["amount"],
                   lambda amount, **_: f"{float(amount) * 1.08:.2f} USD"),
        SimpleTool("timezone_lookup", "Local time in a city.",
                   {"city": {"type": "string"}}, ["city"],
                   lambda city, **_: f"Local time in {city}: 14:30"),
    ]


def build_mcp():
    crm = {"ACME": {"tier": "enterprise", "owner": "dana@example.com"}}
    tickets = {"ACME": [{"id": "T-77", "title": "SSO fails", "severity": "high"}]}
    return MCPServer(name="crm").register_many([
        MCPTool(
            name="crm_lookup_customer",
            description="Look up a customer record in the CRM by company name.",
            input_schema={"type": "object",
                          "properties": {"company": {"type": "string"}},
                          "required": ["company"]},
            handler=lambda context, company="", **_: json.dumps(
                crm.get(company, {"error": "unknown"})),
            read_only=True,
        ),
        MCPTool(
            name="crm_open_tickets",
            description="List a customer's open support tickets.",
            input_schema={"type": "object",
                          "properties": {"company": {"type": "string"}},
                          "required": ["company"]},
            handler=lambda context, company="", **_: json.dumps(
                tickets.get(company, [])),
            read_only=True,
        ),
    ])


def load_llm():
    spec = importlib.util.spec_from_file_location("bedrock_mantle_provider", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bedrock_mantle_provider"] = module
    spec.loader.exec_module(module)
    module.ensure_registered()
    from shipit_agent.llms import LiteLLMChatLLM

    return LiteLLMChatLLM(model=MODEL)


def main() -> int:
    if not Path(PROVIDER).exists():
        print(f"provider checkout not found: {PROVIDER}")
        return 1

    agent = Agent(
        llm=load_llm(),
        tools=build_tools(),
        mcps=[build_mcp()],
        deferred_tools=True,
        parallel_tool_execution=True,
        max_tool_concurrency=4,
        progress_summaries=True,
        max_iterations=8,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        retry_policy=RetryPolicy(request_timeout=180.0),
    )

    prompt = (
        "Look up ACME in the CRM and their open tickets, check the weather in "
        "Berlin, total the open orders worth at least 500 EUR and convert that "
        "total to USD. If anything is ambiguous, ask me. Then summarize."
    )

    counts: dict[str, int] = {}
    start = time.monotonic()
    log = open(LOG_PATH, "w")
    print(f"=== streaming {MODEL} — EVERY AgentEvent, verbatim ===\n")

    def _safe(value):
        """JSON-safe copy of any payload value, without dropping anything."""
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return repr(value)

    index = 0
    for event in agent.stream(prompt):
        index += 1
        counts[event.type] = counts.get(event.type, 0) + 1
        elapsed = time.monotonic() - start
        # The COMPLETE event, unedited: index, timestamp, type, message, and
        # the full payload verbatim (every key, every value).
        record = {
            "i": index,
            "t": round(elapsed, 3),
            "type": event.type,
            "message": event.message,
            "payload": {k: _safe(v) for k, v in event.payload.items()},
        }
        line = json.dumps(record, ensure_ascii=False)
        log.write(line + "\n")
        log.flush()
        # Print the exact same record to stdout — nothing filtered, nothing
        # summarized. This is precisely what the agent emitted.
        print(line, flush=True)

    log.close()
    total = time.monotonic() - start

    print(f"\n=== {sum(counts.values())} events in {total:.1f}s ===")
    for etype in sorted(counts):
        print(f"  {counts[etype]:>4} {etype}")
    print(f"\nFull verbatim JSONL log: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
