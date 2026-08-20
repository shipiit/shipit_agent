"""Ten-turn Agent.stream() memory/tool/MCP gauntlet for Bedrock Gemma 4.

This is intentionally manual: it uses the real provider and costs tokens.
It keeps one plain ``Agent(...)`` instance for all turns and checks later
answers against facts established by earlier model and tool turns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from live_streaming_gemma import build_mcp, build_tools, load_llm
from shipit_agent.agent import Agent
from shipit_agent.policies import RetryPolicy


@dataclass(frozen=True)
class Turn:
    prompt: str
    expected: tuple[str, ...] = ()
    expected_tools: tuple[str, ...] = ()


TURNS = (
    Turn("Remember these session facts: project codename ORBIT-MAP and owner Mira. Acknowledge briefly.", ("orbit-map", "mira")),
    Turn("Use the calculator tool to calculate 17 * 23. Remember the result.", ("391",), ("calculator",)),
    Turn("Use the CRM MCP to look up ACME. Remember its tier and owner.", ("enterprise", "dana"), ("crm_lookup_customer",)),
    Turn("Using the calculation from turn 2, add 9. Do not recalculate 17 * 23.", ("400",)),
    Turn("Use the weather tool for Berlin and remember the conditions.", ("berlin", "21"), ("weather_lookup",)),
    Turn("Without calling tools, summarize the facts established in turns 1, 3, and 5.", ("orbit-map", "mira", "enterprise", "dana", "berlin", "21")),
    Turn("Use the CRM MCP to retrieve ACME's open tickets. Remember the ticket id and severity.", ("t-77", "high"), ("crm_open_tickets",)),
    Turn("Cross-reference turns 3 and 7: who owns ACME and which high-severity ticket is open?", ("dana", "t-77", "high")),
    Turn("Use the orders tool for open orders worth at least 500 EUR. Total them, then use the currency tool to convert the total to USD.", ("1950", "2106"), ("orders_db_query", "currency_convert")),
    Turn("Final memory check without tools: give the codename, project owner, turn-2 calculation, ACME owner and tier, ticket id and severity, Berlin weather, and the EUR/USD totals from turn 9.", ("orbit-map", "mira", "391", "dana", "enterprise", "t-77", "high", "berlin", "21", "1950", "2106")),
    Turn("Without tools, list only the facts established in user turns 2, 5, 7, and 9.", ("391", "berlin", "21", "t-77", "high", "1950", "2106")),
    Turn("Use the timezone tool for Warsaw and remember the local time.", ("warsaw", "14:30"), ("timezone_lookup",)),
    Turn("Without tools, cross-reference Berlin's remembered weather with Warsaw's remembered local time.", ("berlin", "21", "warsaw", "14:30")),
    Turn("Use the calculator tool to add 94 to the remembered USD total from user turn 9.", ("2200",), ("calculator",)),
    Turn("Without tools, state the user-turn-14 result and ACME's owner.", ("2200", "dana")),
    Turn("Use the CRM MCP to re-check ACME's current owner and tier.", ("dana", "enterprise"), ("crm_lookup_customer",)),
    Turn("Use the currency tool to convert exactly 100 EUR to USD and remember it.", ("108",), ("currency_convert",)),
    Turn("Without tools, combine the facts from user turns 12, 14, and 17.", ("warsaw", "14:30", "2200", "108")),
    Turn("Without tools, correct this claim using session evidence: Mira owns ACME.", ("mira", "dana")),
    Turn("Final 20-turn memory audit without tools: codename and project owner; calculations 391, 400, and 2200; ACME owner/tier and T-77 severity; Berlin weather; turn-9 EUR/USD totals; Warsaw time; and the 100-EUR conversion.", ("orbit-map", "mira", "391", "400", "2200", "dana", "enterprise", "t-77", "high", "berlin", "21", "1950", "2106", "warsaw", "14:30", "108")),
)


def main() -> int:
    # This gauntlet advertises its complete, small tool set. Catalog discovery
    # and interactive input are tested elsewhere; including those meta-tools
    # here gives a small model an irrelevant escape hatch after it already has
    # the requested result.
    tools = [
        tool for tool in build_tools()
        if getattr(tool, "name", "") not in {"tool_search", "ask_user"}
    ]
    agent = Agent(
        llm=load_llm(),
        tools=tools,
        mcps=[build_mcp()],
        parallel_tool_execution=True,
        max_tool_concurrency=4,
        max_iterations=7,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        retry_policy=RetryPolicy(request_timeout=180.0),
    )
    failures: list[str] = []
    total_usage = 0
    session_id = agent.session_id
    try:
        for number, turn in enumerate(TURNS, start=1):
            answer = ""
            tool_names: list[str] = []
            failed = ""
            usage = 0
            for event in agent.stream(turn.prompt):
                if event.payload.get("session_id") not in (None, session_id):
                    failures.append(f"turn {number}: session id changed")
                if event.type == "tool_called":
                    tool_names.append(str(event.payload.get("tool", "")))
                elif event.type == "run_failed":
                    failed = str(event.payload.get("error", "unknown error"))
                elif event.type == "run_completed":
                    answer = str(event.payload.get("output", ""))
                    usage = int((event.payload.get("usage") or {}).get("total_tokens", 0) or 0)
            total_usage += usage
            lower = answer.lower().replace(",", "")
            missing = [value for value in turn.expected if value not in lower]
            missing_tools = [name for name in turn.expected_tools if name not in tool_names]
            ok = not failed and not missing and not missing_tools
            if not ok:
                failures.append(
                    f"turn {number}: error={failed!r}, missing={missing!r}, "
                    f"missing_tools={missing_tools!r}, answer={answer[:500]!r}"
                )
            print(json.dumps({
                "turn": number,
                "ok": ok,
                "tools": tool_names,
                "tokens": usage,
                "answer": answer,
            }, ensure_ascii=False))
    finally:
        agent.close()

    print(json.dumps({
        "session_id_stable": agent.session_id == session_id,
        "turns": len(TURNS),
        "total_tokens": total_usage,
        "failures": failures,
    }, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
