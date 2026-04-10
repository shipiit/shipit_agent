from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CreatedTool:
    """Record of a tool created at runtime."""

    name: str
    description: str
    code: str


class AdaptiveAgent:
    """Agent that can create new tools at runtime.

    When the agent needs a capability it doesn't have, it writes
    Python code to create a new tool and registers it for use.

    Example::

        agent = AdaptiveAgent(
            llm=llm,
            tools=[code_exec],
            can_create_tools=True,
        )
        result = agent.run("Parse and analyze the CSV at /data/sales.csv")
        print(result.created_tools)  # ["csv_parser"]
    """

    def __init__(
        self,
        *,
        llm: Any,
        tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        can_create_tools: bool = True,
        sandbox: bool = True,
        use_builtins: bool = False,
        prompt: str = "You are a helpful assistant.",
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.tools = list(tools or [])
        self.mcps = mcps or []
        self.can_create_tools = can_create_tools
        self.sandbox = sandbox
        self.use_builtins = use_builtins
        self.prompt = prompt
        self.agent_kwargs = agent_kwargs
        self.created_tools: list[CreatedTool] = []

    @classmethod
    def with_builtins(cls, *, llm: Any, mcps: list[Any] | None = None, **kwargs: Any) -> "AdaptiveAgent":
        """Create an AdaptiveAgent with all built-in tools."""
        return cls(llm=llm, mcps=mcps, use_builtins=True, **kwargs)

    def create_tool(self, name: str, description: str, code: str) -> Any:
        """Dynamically create and register a tool from Python code."""
        import textwrap
        from shipit_agent import FunctionTool

        # Auto-dedent so indented code strings (e.g. from notebooks) work
        clean_code = textwrap.dedent(code)
        namespace: dict[str, Any] = {}
        exec(clean_code, namespace)  # noqa: S102 — intentional for dynamic tool creation

        # Find the function in the namespace
        fn = None
        for val in namespace.values():
            if callable(val) and not isinstance(val, type):
                fn = val
                break

        if fn is None:
            raise ValueError(f"No callable function found in tool code for '{name}'")

        tool = FunctionTool.from_callable(fn, name=name, description=description)
        self.tools.append(tool)
        self.created_tools.append(CreatedTool(name=name, description=description, code=code))
        return tool

    def run(self, task: str) -> Any:
        from shipit_agent.agent import Agent

        if self.use_builtins:
            agent = Agent.with_builtins(llm=self.llm, prompt=self.prompt, mcps=self.mcps, **self.agent_kwargs)
            # Add dynamically created tools
            agent.tools.extend(self.tools)
        else:
            agent = Agent(llm=self.llm, prompt=self.prompt, tools=list(self.tools), mcps=self.mcps, **self.agent_kwargs)
        return agent.run(task)

    def stream(self, task: str):
        """Run the adaptive agent and yield events."""
        from shipit_agent.agent import Agent
        from shipit_agent.models import AgentEvent

        yield AgentEvent(type="run_started", message=f"AdaptiveAgent: {task[:80]}", payload={"created_tools": [t.name for t in self.created_tools]})

        if self.use_builtins:
            agent = Agent.with_builtins(llm=self.llm, prompt=self.prompt, mcps=self.mcps, **self.agent_kwargs)
            agent.tools.extend(self.tools)
        else:
            agent = Agent(llm=self.llm, prompt=self.prompt, tools=list(self.tools), mcps=self.mcps, **self.agent_kwargs)

        for event in agent.stream(task):
            yield event
