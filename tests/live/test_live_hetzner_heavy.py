"""Heavy real-user live tests — Hetzner inference (OpenAI-compatible API).

One agent, twelve capabilities (nine local tools + a three-tool CRM MCP
server), deferred tool loading on — the Claude-Code working shape. Each
model answers three real-user asks:

1. multi-tool orchestration (CRM lookup → tickets → email),
2. data + arithmetic (query orders, total them),
3. a plain question that needs NO tools (token discipline: the agent must
   answer directly, not go tool-shopping).

Gated on HETZNER_API_KEY; run with:

    HETZNER_API_KEY=... python -m pytest tests/live/test_live_hetzner_heavy.py -q -rs
"""

from __future__ import annotations

import json
import os

import pytest

from shipit_agent import MCPServer, MCPTool
from shipit_agent.agent import Agent
from shipit_agent.policies import RetryPolicy
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool

BASE_URL = os.getenv("HETZNER_BASE_URL", "https://inference.hetzner.com/api/v1")
MODELS = [
    "DeepSeek-V4-Flash-0731",
    "GLM-5.2-NVFP4",
    "Kimi-K2.7-Code",
    "Qwen/Qwen3.6-35B-A3B-FP8",
]

pytestmark = pytest.mark.skipif(
    not os.getenv("HETZNER_API_KEY"), reason="HETZNER_API_KEY not set"
)


# ── the tool fleet ───────────────────────────────────────────────────────


class SimpleTool:
    def __init__(self, name, description, params, required, fn):
        self.name = name
        self.description = description
        self._params = params
        self._required = required
        self._fn = fn
        self.calls: list[dict] = []

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
        self.calls.append(dict(kwargs))
        return ToolOutput(text=self._fn(**kwargs), metadata={})


ORDERS = [
    {"id": "A-1", "customer": "ACME", "value_eur": 750, "status": "open"},
    {"id": "A-2", "customer": "ACME", "value_eur": 1200, "status": "open"},
    {"id": "B-1", "customer": "Globex", "value_eur": 90, "status": "open"},
    {"id": "B-2", "customer": "Globex", "value_eur": 4000, "status": "closed"},
]

CRM = {
    "ACME": {"tier": "enterprise", "owner": "dana@example.com", "open_tickets": 2},
    "Globex": {"tier": "starter", "owner": "lee@example.com", "open_tickets": 0},
}

TICKETS = {
    "ACME": [
        {"id": "T-77", "title": "SSO login fails", "severity": "high"},
        {"id": "T-81", "title": "Export times out", "severity": "medium"},
    ],
    "Globex": [],
}


def build_fleet():
    """Nine local tools + one MCP server with three CRM tools."""
    sent_emails: list[dict] = []

    def _weather(city, **_):
        return f"Weather in {city}: 21°C, clear skies."

    def _calc(expression, **_):
        allowed = set("0123456789+-*/(). ")
        if not expression or set(expression) - allowed:
            return "Error: only arithmetic expressions are supported."
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307

    def _orders(min_value_eur=0, status="", **_):
        rows = [
            r
            for r in ORDERS
            if r["value_eur"] >= float(min_value_eur or 0)
            and (not status or r["status"] == status)
        ]
        return json.dumps(rows)

    def _email(to, subject="", body="", **_):
        sent_emails.append({"to": to, "subject": subject, "body": body})
        return f"Email sent to {to}."

    def _slack(channel, text, **_):
        return f"Posted to {channel}: {text[:80]}"

    def _calendar(date="", **_):
        return json.dumps([{"time": "10:00", "title": "Ops standup"}])

    def _notes_write(title, content, **_):
        return f"Note '{title}' saved ({len(content)} chars)."

    def _fx(amount, from_currency, to_currency, **_):
        rate = 1.08 if (from_currency, to_currency) == ("EUR", "USD") else 1.0
        return f"{float(amount) * rate:.2f} {to_currency}"

    tools = [
        ToolSearchTool(),
        SimpleTool("weather_lookup", "Current weather for a city.",
                   {"city": {"type": "string"}}, ["city"], _weather),
        SimpleTool("calculator", "Evaluate an arithmetic expression.",
                   {"expression": {"type": "string"}}, ["expression"], _calc),
        SimpleTool("orders_db_query",
                   "Query the orders database. Filter by minimum value and status.",
                   {"min_value_eur": {"type": "number"},
                    "status": {"type": "string"}}, [], _orders),
        SimpleTool("send_email", "Send an email.",
                   {"to": {"type": "string"}, "subject": {"type": "string"},
                    "body": {"type": "string"}}, ["to"], _email),
        SimpleTool("slack_post", "Post a message to a Slack channel.",
                   {"channel": {"type": "string"}, "text": {"type": "string"}},
                   ["channel", "text"], _slack),
        SimpleTool("calendar_events", "List calendar events for a date.",
                   {"date": {"type": "string"}}, [], _calendar),
        SimpleTool("notes_write", "Save a note.",
                   {"title": {"type": "string"}, "content": {"type": "string"}},
                   ["title", "content"], _notes_write),
        SimpleTool("currency_convert", "Convert an amount between currencies.",
                   {"amount": {"type": "number"},
                    "from_currency": {"type": "string"},
                    "to_currency": {"type": "string"}},
                   ["amount", "from_currency", "to_currency"], _fx),
    ]

    crm = MCPServer(name="crm").register_many([
        MCPTool(
            name="crm_lookup_customer",
            description="Look up a customer record in the CRM by company name.",
            input_schema={"type": "object",
                          "properties": {"company": {"type": "string"}},
                          "required": ["company"]},
            handler=lambda context, company="", **_: json.dumps(
                CRM.get(company, {"error": f"no customer named {company!r}"})
            ),
        ),
        MCPTool(
            name="crm_open_tickets",
            description="List a customer's open support tickets.",
            input_schema={"type": "object",
                          "properties": {"company": {"type": "string"}},
                          "required": ["company"]},
            handler=lambda context, company="", **_: json.dumps(
                TICKETS.get(company, [])
            ),
        ),
        MCPTool(
            name="crm_update_ticket",
            description="Update a support ticket's status.",
            input_schema={"type": "object",
                          "properties": {"ticket_id": {"type": "string"},
                                         "status": {"type": "string"}},
                          "required": ["ticket_id", "status"]},
            handler=lambda context, ticket_id="", status="", **_: (
                f"Ticket {ticket_id} set to {status}."
            ),
        ),
    ])

    return tools, [crm], sent_emails


def build_agent(model: str):
    from shipit_agent.llms import OpenAIChatLLM

    tools, mcps, sent_emails = build_fleet()
    agent = Agent(
        llm=OpenAIChatLLM(
            model=model,
            api_key=os.environ["HETZNER_API_KEY"],
            base_url=BASE_URL,
        ),
        tools=tools,
        mcps=mcps,
        deferred_tools=True,
        max_iterations=8,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        retry_policy=RetryPolicy(request_timeout=180.0),
    )
    return agent, sent_emails


def _report(model, label, result):
    ran = [r.name for r in result.tool_results]
    ticks = [e for e in result.events if e.type == "usage_tick"]
    tokens = ticks[-1].payload["usage"].get("total_tokens", 0) if ticks else 0
    print(f"\n[{model}] {label}: tools={ran} tokens={tokens} "
          f"answer={result.output[:160]!r}")
    return ran, tokens


@pytest.mark.parametrize("model", MODELS)
def test_heavy_multi_tool_crm_flow(model):
    """CRM lookup → tickets → email: cross-tool orchestration through
    deferred loading, with the CRM living behind MCP."""
    agent, sent_emails = build_agent(model)
    result = agent.run(
        "Look up the customer ACME in the CRM, check their open support "
        "tickets, then email a one-line status summary to ops@example.com. "
        "Confirm what you sent."
    )
    ran, tokens = _report(model, "crm-flow", result)
    assert any(name.startswith("crm_") for name in ran), f"no CRM tool ran: {ran}"
    assert sent_emails, f"no email sent (ran: {ran})"
    assert "ops@example.com" in sent_emails[0]["to"]
    assert tokens > 0


@pytest.mark.parametrize("model", MODELS)
def test_heavy_data_and_math(model):
    """Query + arithmetic: the answer must contain the true total (1950)."""
    agent, _ = build_agent(model)
    result = agent.run(
        "Query the orders database for OPEN orders worth at least 500 EUR "
        "and tell me their combined total value in EUR."
    )
    ran, _tokens = _report(model, "data-math", result)
    assert "orders_db_query" in ran, f"database never queried: {ran}"
    assert "1950" in result.output.replace(",", "").replace(".", ""), (
        f"wrong total in answer: {result.output[:200]!r}"
    )


@pytest.mark.parametrize("model", MODELS)
def test_no_tools_for_a_plain_question(model):
    """Token discipline: a general-knowledge question must not go
    tool-shopping — twelve capabilities available, zero used."""
    agent, _ = build_agent(model)
    result = agent.run("What is the capital of France? Answer in one word.")
    ran, tokens = _report(model, "no-tools", result)
    assert "paris" in result.output.lower()
    action_tools = [n for n in ran if n != "tool_search"]
    assert action_tools == [], f"burned tools on a plain question: {ran}"
    assert tokens > 0
