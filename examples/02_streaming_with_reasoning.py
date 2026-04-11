"""
02 — Live streaming with reasoning ("Thinking") events.

Shows how to consume `agent.stream()` to render live progress, including
the model's thinking blocks (when the underlying model surfaces them —
o1/o3/gpt-5/Claude/gpt-oss/DeepSeek R1).

This is the recommended pattern for any UI that wants to show:
  - 🧠 What the model is thinking right now
  - ▶ Which tool it's about to call
  - ✓ Tool outputs as they arrive
  - 📝 The final answer

Run:
    python examples/02_streaming_with_reasoning.py

For best results, use a reasoning-capable model:
    SHIPIT_LLM_PROVIDER=openai SHIPIT_OPENAI_MODEL=o3-mini python examples/02_streaming_with_reasoning.py
    SHIPIT_LLM_PROVIDER=bedrock python examples/02_streaming_with_reasoning.py
"""

from __future__ import annotations

import sys

from examples.run_multi_tool_agent import build_demo_agent, build_llm_from_env

# ANSI colors for terminal output
DIM = "\033[2m"
BOLD = "\033[1m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
RESET = "\033[0m"


def truncate(value: object, n: int = 220) -> str:
    s = str(value).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def render_event(event) -> None:
    """Pretty-print one event with color and a leading icon."""
    t = event.type
    msg = event.message or ""
    p = event.payload or {}

    if t == "run_started":
        print(
            f"{BOLD}{BLUE}▶ run started{RESET}  {DIM}{truncate(p.get('prompt', ''), 80)}{RESET}"
        )
    elif t == "step_started":
        iteration = p.get("iteration", "?")
        tools = p.get("tool_count", "?")
        print(f"\n{DIM}─── iteration {iteration} ({tools} tools) ───{RESET}")
    elif t == "reasoning_started":
        print(f"{MAGENTA}🧠 thinking…{RESET}", end=" ", flush=True)
    elif t == "reasoning_completed":
        content = truncate(p.get("content", ""), 300)
        print(f"\n{MAGENTA}🧠 {content}{RESET}")
    elif t == "tool_called":
        args = truncate(p.get("arguments", {}), 100)
        print(f"{CYAN}▶ {msg}{RESET}  {DIM}{args}{RESET}")
    elif t == "tool_completed":
        output = truncate(p.get("output", ""), 120)
        print(f"{GREEN}✓ {msg}{RESET}  {DIM}{output}{RESET}")
    elif t == "tool_failed":
        print(f"{YELLOW}✗ {msg}{RESET}  {DIM}{truncate(p.get('error', ''))}{RESET}")
    elif t == "run_completed":
        print(f"\n{BOLD}{GREEN}━━━ FINAL ━━━{RESET}")
        print(p.get("output", "") or "(no output)")
    else:
        print(f"{DIM}[{t}] {msg}{RESET}")


def main() -> None:
    llm = build_llm_from_env()
    agent = build_demo_agent(llm=llm)

    prompt = (
        "What is 137 * 89? Use the code interpreter to verify. "
        "Then explain why multiplication is commutative."
    )

    print(f"\n{BOLD}Prompt:{RESET} {prompt}\n")
    print(f"{BOLD}Streaming events as they arrive:{RESET}\n")

    event_count = 0
    for event in agent.stream(prompt):
        render_event(event)
        event_count += 1

    print(f"\n{DIM}Stream complete — {event_count} events received.{RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted.", file=sys.stderr)
        sys.exit(130)
