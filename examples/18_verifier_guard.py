"""
18 — Pre-tool verifier guard.

A ``PreToolVerifier`` asks a (small/cheap) verifier LLM to ALLOW, VETO or
REWRITE each proposed tool call *before* it runs — a safety net against the
main model doing something destructive. The verifier fails **open**: if the
judge errors, the call is allowed, so the guard can never deadlock the agent.

This script uses a scripted judge LLM so it runs offline.

Run:
    python examples/18_verifier_guard.py
"""

from __future__ import annotations

import json

from shipit_agent.llms.base import LLMResponse
from shipit_agent.verifier import PreToolVerifier, VerifierConfig


class _ScriptedJudge:
    """Vetoes destructive shell commands, allows everything else."""

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        text = " ".join(m.content or "" for m in messages).lower()
        if "rm -rf" in text or "drop table" in text:
            verdict = {
                "verdict": "veto",
                "reason": "Destructive operation blocked by policy.",
                "confidence": 0.95,
            }
        else:
            verdict = {"verdict": "allow", "reason": "looks safe", "confidence": 0.9}
        return LLMResponse(content=json.dumps(verdict))


def main() -> None:
    verifier = PreToolVerifier(
        llm=_ScriptedJudge(),
        config=VerifierConfig(veto_min_confidence=0.6),
    )

    print("─" * 60)
    print("  Pre-tool verifier decisions")
    print("─" * 60)

    proposals = [
        ("bash", {"command": "ls -la"}),
        ("bash", {"command": "rm -rf /"}),
        ("sql", {"query": "SELECT * FROM users"}),
        ("sql", {"query": "DROP TABLE users"}),
    ]
    for tool_name, args in proposals:
        decision = verifier.check(
            tool_name=tool_name,
            tool_args=args,
            goal="Help the user safely.",
        )
        verdict = decision.verdict.value if hasattr(decision.verdict, "value") else decision.verdict
        flag = "✅" if str(verdict).lower() == "allow" else "⛔"
        print(f"  {flag} {tool_name}({args}) → {verdict}: {decision.reason}")


if __name__ == "__main__":
    main()
