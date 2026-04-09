from __future__ import annotations

from shipit_agent import Agent, get_builtin_tools
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.tools import DecisionMatrixTool, EvidenceSynthesisTool, ThoughtDecompositionTool


llm = SimpleEchoLLM()
tools = get_builtin_tools(llm=llm, workspace_root=".shipit_workspace")
tools.extend(
    [
        ThoughtDecompositionTool(),
        EvidenceSynthesisTool(),
        DecisionMatrixTool(),
    ]
)

agent = Agent(
    llm=llm,
    tools=tools,
    name="reasoning-agent",
    description="A stronger workspace agent with structured decomposition, synthesis, and decision tools.",
)

if __name__ == "__main__":
    result = agent.run("Break down a project migration, synthesize the evidence, and recommend the best path.")
    print(result.output)
