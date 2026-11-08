"""create_deep_agent: build a DeepAgent from keyword options."""

from __future__ import annotations

from typing import Any

from ..goal_agent import Goal
from .factory import DeepAgent
from .prompt import DEEP_AGENT_PROMPT


def create_deep_agent(
    *,
    llm: Any,
    tools: list[Any] | None = None,
    agents: Any = None,
    system_prompt: str = DEEP_AGENT_PROMPT,
    rag: Any = None,
    use_builtins: bool = False,
    verify: bool = False,
    reflect: bool = False,
    goal: Goal | None = None,
    memory: Any = None,
    max_iterations: int = 8,
    verifier: Any = None,
    **kwargs: Any,
) -> DeepAgent:
    """LangChain-style ``create_deep_agent`` factory function — but more powerful.

    Drop-in alternative to :class:`DeepAgent` with the keyword names
    LangChain users expect plus the power-user flags this library
    exposes.

    Example::

        from shipit_agent.deep import create_deep_agent

        def get_weather(city: str) -> str:
            \"\"\"Get weather for a given city.\"\"\"
            return f"It's always sunny in {city}!"

        agent = create_deep_agent(
            tools=[get_weather],
            llm=llm,
            system_prompt="You are a helpful weather assistant.",
            verify=True,
            reflect=True,
            rag=my_rag,
        )

        result = agent.run("what is the weather in sf")

    Sub-agents — wire your own agents as delegates::

        researcher = Agent.with_builtins(llm=llm, prompt="You research.")
        writer     = Agent.with_builtins(llm=llm, prompt="You write.")
        critic     = ReflectiveAgent.with_builtins(llm=llm)

        agent = create_deep_agent(
            llm=llm,
            agents=[researcher, writer, critic],   # ← named sub-agents
            use_builtins=True,
        )

        # The deep agent now has a `delegate_to_agent` tool it can call
        # to hand off well-scoped sub-tasks to any of the named agents.
        # This makes it behave like a Supervisor — but more powerful,
        # since it still has the full deep-agent toolset itself.
        result = agent.run("Investigate the auth bug, draft a fix, then review.")
    """
    explicit_extra_tools = list(kwargs.pop("extra_tools", []) or [])
    extra_tools: list[Any] = []
    for tool in tools or []:
        if callable(tool) and not hasattr(tool, "schema"):
            from shipit_agent.tools import FunctionTool

            extra_tools.append(FunctionTool.from_callable(tool))
        else:
            extra_tools.append(tool)
    extra_tools.extend(explicit_extra_tools)

    factory = DeepAgent.with_builtins if use_builtins else DeepAgent
    return factory(
        llm=llm,
        prompt=system_prompt,
        extra_tools=extra_tools,
        agents=agents,
        rag=rag,
        verify=verify,
        reflect=reflect,
        goal=goal,
        memory=memory,
        max_iterations=max_iterations,
        verifier=verifier,
        **kwargs,
    )

