"""The agent types the chat can run, and driving any of them the same way."""

from __future__ import annotations

import os
from typing import Any

AGENT_TYPES = (
    "agent",
    "deep",
    "goal",
    "reflective",
    "adaptive",
    "supervisor",
    "persistent",
)


def make_agent(
    agent_type: str,
    *,
    llm: Any,
    rag: Any = None,
    workspace_root: str = ".shipit_workspace",
    use_builtins: bool = True,
    goal_objective: str | None = None,
    goal_criteria: list[str] | None = None,
    reflect: bool = False,
    verify: bool = False,
) -> Any:
    """Build an agent of the requested type, fully wired for chat."""
    from shipit_agent import Agent
    from shipit_agent.deep import (
        AdaptiveAgent,
        DeepAgent,
        Goal,
        GoalAgent,
        PersistentAgent,
        ReflectiveAgent,
        Supervisor,
    )

    agent_type = agent_type.lower()
    if agent_type == "agent":
        if use_builtins:
            return Agent.with_builtins(llm=llm, workspace_root=workspace_root, rag=rag)
        return Agent(llm=llm, rag=rag)

    if agent_type == "deep":
        return (DeepAgent.with_builtins if use_builtins else DeepAgent)(
            llm=llm,
            workspace_root=workspace_root,
            rag=rag,
            reflect=reflect,
            verify=verify,
        )

    if agent_type == "goal":
        objective = goal_objective or "Help the user with their request."
        criteria = goal_criteria or ["Answer addresses the user's question."]
        return GoalAgent.with_builtins(
            llm=llm,
            goal=Goal(objective=objective, success_criteria=criteria),
            rag=rag,
        )

    if agent_type == "reflective":
        return ReflectiveAgent.with_builtins(llm=llm, rag=rag)

    if agent_type == "adaptive":
        return AdaptiveAgent.with_builtins(llm=llm, rag=rag)

    if agent_type == "supervisor":
        return Supervisor.with_builtins(
            llm=llm,
            worker_configs=[
                {
                    "name": "researcher",
                    "prompt": "You research information thoroughly.",
                },
                {"name": "writer", "prompt": "You write clear, concise answers."},
            ],
            rag=rag,
        )

    if agent_type == "persistent":
        return PersistentAgent(
            llm=llm,
            checkpoint_dir=os.path.join(workspace_root, "checkpoints"),
            rag=rag,
        )

    raise ValueError(f"Unknown agent type: {agent_type}. Choose from {AGENT_TYPES}.")


def stream_any_agent(agent: Any, user_text: str):
    """Stream from any agent type, normalising the interface."""
    if hasattr(agent, "stream"):
        # Most agents take user_text; some (GoalAgent) ignore the prompt.
        try:
            yield from agent.stream(user_text)
            return
        except TypeError:
            yield from agent.stream()
            return
    # Fallback: synchronous run
    result = run_any_agent(agent, user_text)
    from shipit_agent.core.models import AgentEvent

    yield AgentEvent(
        type="run_completed",
        message="run completed",
        payload={"output": getattr(result, "output", str(result))},
    )


def run_any_agent(agent: Any, user_text: str) -> Any:
    """Run *agent* on *user_text*, whichever agent type it is."""
    if hasattr(agent, "run"):
        try:
            return agent.run(user_text)
        except TypeError:
            return agent.run()
    raise TypeError(f"Agent {agent.__class__.__name__} has no run() method")


def agent_tools(agent: Any) -> list[Any]:
    """The tools *agent* has, whichever agent type it is."""
    if hasattr(agent, "tools"):
        return list(agent.tools)
    if hasattr(agent, "agent") and hasattr(agent.agent, "tools"):
        return list(agent.agent.tools)
    return []


def agent_chat_session(agent: Any, *, session_id: str, session_store: Any) -> Any:
    """Return an AgentChatSession-compatible object for the given agent."""
    from shipit_agent.chat_session import AgentChatSession

    inner = agent
    # DeepAgent / wrappers expose .agent for the underlying Agent.
    if hasattr(agent, "agent") and hasattr(agent.agent, "run"):
        inner = agent.agent
    if hasattr(inner, "run") and hasattr(inner, "stream"):
        return AgentChatSession(
            agent=inner,
            session_id=session_id,
            session_store=session_store,
        )
    return None  # Goal/Supervisor/etc. — fall back to direct stream
