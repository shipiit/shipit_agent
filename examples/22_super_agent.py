"""
22 — The super agent: every sector, clean logs, real deliverables.

Four capabilities that turn shipit into a Claude-Code-grade agent for ANY
role — finance, marketing, engineering, design, research, sales, support:

  1. `Agent.for_role("finance-analyst", llm=llm)`
        → 40+ prebuilt sector specialists, one line each.
  2. `connect_mcp("github")`
        → prebuilt MCP catalog (GitHub, Slack, Postgres, filesystem,
          Puppeteer, Brave search, …) on a persistent stdio transport.
  3. `build_document` (built-in tool)
        → polished PDF reports, Excel workbooks with live formulas,
          Word docs, PowerPoint decks, styled HTML.
  4. `format_activity(result)`
        → Claude-Code-style tool cards: name, args, ✓/✗, duration,
          output preview.

Runs fully offline (scripted LLM) so you can see all of it with no keys.

Run:
    python examples/22_super_agent.py
"""

from __future__ import annotations

from shipit_agent import Agent, format_activity, list_mcp_catalog
from shipit_agent.llms.base import LLMResponse, ToolCall


class ScriptedLLM:
    """Calls build_document once, then answers — offline demo driver."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools=None, **_kwargs) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="build_document",
                        arguments={
                            "kind": "xlsx",
                            "title": "Q2 Close",
                            "sheets": [
                                {
                                    "name": "P&L",
                                    "headers": ["Item", "Amount"],
                                    "rows": [
                                        ["Revenue", 124_000],
                                        ["Costs", -78_500],
                                        ["Net", "=B2+B3"],
                                    ],
                                }
                            ],
                        },
                    )
                ]
            )
        return LLMResponse(
            content="Q2 close workbook is ready — net income formula included."
        )


def main() -> None:
    print("1) Sector specialists — one line each")
    for role in ("finance-analyst", "marketing-writer", "researcher",
                 "figma-designer", "sales-rep", "generalist-developer"):
        agent = Agent.for_role(role, llm=ScriptedLLM())
        print(f"   • {role:<22} {len(agent.tools):>2} tools · "
              f"{agent.metadata['category']}")

    print("\n2) Prebuilt MCP catalog — connect_mcp(name)")
    for entry in list_mcp_catalog():
        env = f"  (needs {', '.join(entry.required_env)})" if entry.required_env else ""
        print(f"   • {entry.name:<14} {entry.description}{env}")

    print("\n3+4) Run the finance agent → real Excel file, clean activity log")
    agent = Agent.for_role("finance-analyst", llm=ScriptedLLM())
    result = agent.run("Close Q2 and hand me the workbook.")
    print()
    print("   " + format_activity(result).replace("\n", "\n   "))
    print(f"\n   Final answer: {result.output}")


if __name__ == "__main__":
    main()
