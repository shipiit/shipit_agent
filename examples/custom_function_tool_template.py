from __future__ import annotations

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import SimpleEchoLLM


def workspace_summary(workspace_name: str) -> str:
    return f"Workspace '{workspace_name}' should prefer explicit tools, verification, and saved artifacts."


agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[
        FunctionTool.from_callable(
            workspace_summary,
            name="workspace_summary",
            description="Return a short summary of how a workspace agent should operate.",
        )
    ],
)

if __name__ == "__main__":
    result = agent.run("Summarize the workspace style.")
    print(result.output)
