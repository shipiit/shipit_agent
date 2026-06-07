"""
15 — Multi-turn chat sessions stay clean.

``agent.chat_session(session_id=...)`` keeps a running conversation. Across
many turns the message history grows linearly (one user + one assistant per
turn) and carries exactly **one** leading system message — it never stacks a
fresh system prompt every turn.

This script runs offline with the local echo LLM.

Run:
    python examples/15_multi_turn_memory.py
"""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms import ShipitLLM


def main() -> None:
    agent = Agent(llm=ShipitLLM(), auto_use_skills=False)
    session = agent.chat_session(session_id="demo-conversation")

    turns = [
        "Hi, my name is Ada.",
        "I'm working on a compiler.",
        "What was my name again?",
    ]

    print("─" * 60)
    print("  Multi-turn chat session")
    print("─" * 60)
    for turn in turns:
        result = session.send(turn)
        print(f"\n  you   > {turn}")
        print(f"  agent > {result.output.splitlines()[-1][:80]}")

    history = session.history()
    system_messages = [m for m in history if m.role == "system"]
    print("\n  ── session health ──")
    print(f"  total messages:  {len(history)}")
    print(f"  system messages: {len(system_messages)}  (expected: 1)")
    print(f"  leading role:    {history[0].role}")
    assert len(system_messages) == 1, "system prompt should never accumulate"


if __name__ == "__main__":
    main()
