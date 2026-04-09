"""
01 — Hello, agent.

The shortest possible runnable example. Builds an agent with all built-in
tools, asks it a single question, prints the answer.

Run:
    python examples/01_hello_agent.py

Requires:
    pip install 'shipit-agent[openai]'
    OPENAI_API_KEY in your environment or .env

Or for any other provider, edit `.env` to set SHIPIT_LLM_PROVIDER=...
"""
from __future__ import annotations

from examples.run_multi_tool_agent import build_demo_agent, build_llm_from_env


def main() -> None:
    # build_llm_from_env auto-loads .env walking upward from CWD.
    # Honors SHIPIT_LLM_PROVIDER (defaults to bedrock).
    llm = build_llm_from_env()

    # build_demo_agent attaches every built-in tool: web_search, open_url,
    # tool_search, ask_user, code_interpreter, memory, planner, and more.
    agent = build_demo_agent(llm=llm)

    result = agent.run("What is 17 * 23? Use the code interpreter to be sure.")

    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(result.output)
    print("\n" + "=" * 60)
    print(f"Tool calls: {len(result.tool_results)}")
    for tr in result.tool_results:
        print(f"  • {tr.name}")


if __name__ == "__main__":
    main()
