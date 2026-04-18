from __future__ import annotations

import os
import sys
from pathlib import Path

from shipit_agent import (
    Agent,
    DEFAULT_AGENT_PROMPT,
    FileMemoryStore,
    FileSessionStore,
    FileTraceStore,
    FunctionTool,
    Message,
    get_builtin_tools,
)
from shipit_agent.llms import (
    build_llm_from_env as _build_llm_from_env,
    load_env_file as _load_env_file,
)

DEFAULT_WORKSPACE = ".shipit_workspace"


def build_llm_from_env(provider: str | None = None):
    return _build_llm_from_env(provider)


def load_env_file(path=None):
    return _load_env_file(path)


def project_context(**_ignored) -> str:
    # Accept and ignore stray kwargs — some LLMs hallucinate an `action` argument
    # for zero-arg tools because the generated JSON schema has no properties.
    return (
        "This workspace uses SHIPIT Agent for tool-using workflows. "
        "Prefer grounded answers, explain tradeoffs clearly, and use tools before guessing."
    )


def add_numbers(a: int, b: int, **_ignored) -> str:
    return str(int(a) + int(b))


def build_demo_tools(*, llm, workspace_root: str):
    tools = get_builtin_tools(
        llm=llm,
        workspace_root=workspace_root,
        web_search_provider=os.getenv("SHIPIT_WEB_SEARCH_PROVIDER", "duckduckgo"),
        web_search_api_key=os.getenv("SHIPIT_WEB_SEARCH_API_KEY"),
    )
    tools.extend(
        [
            FunctionTool.from_callable(
                project_context,
                name="project_context",
                description="Return the local project context and execution style for this agent.",
            ),
            FunctionTool.from_callable(
                add_numbers,
                name="add_numbers",
                description="Add two integers and return the result.",
            ),
        ]
    )
    return tools


def build_demo_agent(
    *,
    llm=None,
    workspace_root: str = DEFAULT_WORKSPACE,
    history: list[Message] | None = None,
) -> Agent:
    workspace = Path(workspace_root)
    workspace.mkdir(parents=True, exist_ok=True)
    active_llm = llm or build_llm_from_env()
    return Agent(
        llm=active_llm,
        prompt=os.getenv("SHIPIT_AGENT_PROMPT", DEFAULT_AGENT_PROMPT),
        name="shipit-demo",
        description="Runnable multi-tool demo agent with memory, sessions, traces, and provider selection.",
        tools=build_demo_tools(llm=active_llm, workspace_root=str(workspace)),
        history=list(history or []),
        memory_store=FileMemoryStore(workspace / "memory.json"),
        session_store=FileSessionStore(workspace / "sessions"),
        trace_store=FileTraceStore(workspace / "traces"),
        session_id=os.getenv("SHIPIT_SESSION_ID", "demo-session"),
        trace_id=os.getenv("SHIPIT_TRACE_ID", "demo-trace"),
    )


def main(argv: list[str] | None = None) -> int:
    load_env_file(".env")
    args = list(argv or sys.argv[1:])
    prompt = " ".join(args).strip() or os.getenv(
        "SHIPIT_PROMPT",
        "Use the available tools to inspect the workspace, gather context, and answer clearly.",
    )
    stream = os.getenv("SHIPIT_STREAM", "0").lower() in {"1", "true", "yes"}
    workspace_root = os.getenv("SHIPIT_WORKSPACE_ROOT", DEFAULT_WORKSPACE)
    agent = build_demo_agent(workspace_root=workspace_root)

    if stream:
        for event in agent.stream(prompt):
            details = f" :: {event.message}" if event.message else ""
            print(f"[{event.type}]{details}")
        return 0

    result = agent.run(prompt)
    print(result.output)
    if result.tool_results:
        print("\nTool results:")
        for item in result.tool_results:
            print(f"- {item.name}: {item.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
