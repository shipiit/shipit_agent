from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM


def test_reasoning_runtime_runs_visible_reasoning_tools() -> None:
    agent = Agent.with_builtins(llm=SimpleEchoLLM())
    result = agent.reason(
        "Choose a deployment path",
        observations=["Blue/green is safer", "Rolling is simpler"],
        options=["Blue/green", "Rolling"],
        criteria=["safety", "operational simplicity"],
        constraints=["Minimize downtime"],
    )
    assert "plan_task" in result.outputs
    assert "decompose_problem" in result.outputs
    assert "synthesize_evidence" in result.outputs
    assert "decision_matrix" in result.outputs
    assert result.events[0].type == "reasoning_started"
    assert result.events[-1].type == "reasoning_completed"
