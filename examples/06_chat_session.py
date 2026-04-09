"""
06 — Persistent chat session with file-backed history.

A conversational agent that remembers previous turns across runs of this
script. Uses FileSessionStore to persist message history to disk so the
agent picks up where it left off the next time you start it.

Run:
    python examples/06_chat_session.py

The first turn introduces yourself, the second turn the agent should
remember your name. Run it twice in a row — even after restarting,
the second run still has the memory from the first.

To reset:
    rm -rf .shipit_sessions/chat-demo
"""
from __future__ import annotations

from pathlib import Path

from shipit_agent import Agent, FileSessionStore

from examples.run_multi_tool_agent import build_demo_agent, build_llm_from_env

SESSION_ROOT = Path(".shipit_sessions")
SESSION_ID = "chat-demo"


def main() -> None:
    llm = build_llm_from_env()

    # Use a persistent file-backed session store. Every agent.run() call
    # appends to disk, and the next run loads the prior history before
    # the new prompt is added.
    session_store = FileSessionStore(root=SESSION_ROOT)

    agent = build_demo_agent(llm=llm)
    agent.session_store = session_store
    agent.session_id = SESSION_ID

    print("─" * 60)
    print("  Persistent chat demo")
    print(f"  Session: {SESSION_ID}")
    print(f"  Storage: {SESSION_ROOT / SESSION_ID}")
    print("─" * 60)

    # Show what the agent already knows from prior runs (if any)
    existing = session_store.load(SESSION_ID)
    if existing and existing.messages:
        print(f"\n📂 Loaded {len(existing.messages)} prior messages from disk")
    else:
        print("\n📂 No prior history (fresh session)")

    print("\nType your message and press Enter. Type 'quit' to exit.\n")

    try:
        while True:
            user_input = input("you  > ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit", "/quit", "/exit"}:
                print("\nGoodbye. Session saved to disk — run me again to continue.")
                break

            result = agent.run(user_input)
            print(f"\nagent > {result.output}\n")

    except (KeyboardInterrupt, EOFError):
        print("\n\nSession saved. Run me again to continue.")


if __name__ == "__main__":
    main()
