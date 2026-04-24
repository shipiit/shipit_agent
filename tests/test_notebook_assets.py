import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_notebook_exists_and_has_expected_cells() -> None:
    notebook_path = ROOT / "notebooks" / "shipit_agent_test_drive.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    cell_sources = ["".join(cell.get("source", [])) for cell in notebook["cells"]]
    joined = "\n".join(cell_sources)
    assert "agent.doctor()" in joined
    assert "build_demo_agent" in joined
    assert "SHIPIT_LLM_PROVIDER" in joined
    assert "agent.chat_session(" in joined
    assert "transport='websocket'" in joined
    assert "transport='sse'" in joined


def test_additional_notebooks_exist_for_major_agent_scenarios() -> None:
    expected = {
        "01_agent_without_tools.ipynb": "Agent(",
        "02_agent_multi_tools.ipynb": "build_demo_agent",
        "03_agent_sessions_and_history.ipynb": "history=[",
        "04_agent_streaming_packets.ipynb": "stream_packets(",
        "05_agent_with_mcp.ipynb": "RemoteMCPServer",
        "06_agent_connectors_gmail_and_others.ipynb": "GmailTool",
        "07_agent_with_human_review.ipynb": "HumanReviewTool",
        "08_agent_with_ask_user.ipynb": "AskUserTool",
        "09_agent_reasoning_and_thinking.ipynb": "agent.reason(",
    }

    for notebook_name, marker in expected.items():
        notebook_path = ROOT / "notebooks" / notebook_name
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        assert notebook["nbformat"] == 4
        joined = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        assert marker in joined


def test_tools_doc_exists_and_mentions_core_tool_topics() -> None:
    tools_doc = (ROOT / "TOOLS.md").read_text(encoding="utf-8")
    assert "SHI" in tools_doc
    assert "How To Create A New Tool" in tools_doc
    assert "GmailTool" in tools_doc
    assert "SlackTool" in tools_doc
    assert "Prompt Files For Tools" in tools_doc
    assert "ThoughtDecompositionTool" in tools_doc
    assert "DecisionMatrixTool" in tools_doc


def _join_code_cells(notebook_path: Path) -> str:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


def test_autopilot_tour_notebooks_use_current_api() -> None:
    """The 44_complete_tour and 45_cost_router notebooks were hitting
    two real API drift bugs — ``AgentRegistry()`` (empty) where
    ``AgentRegistry.default()`` was meant, and ``.all()`` / ``.maxIterations``
    against fields that don't exist on ``AgentDefinition``.

    Lock the fixes in so the next regen of these notebooks can't reintroduce
    them: the tour notebooks MUST reach the bundled prebuilt agents the
    expected way.
    """
    tour = ROOT / "notebooks" / "44_complete_tour.ipynb"
    crouter = ROOT / "notebooks" / "45_cost_router_async_ask_vision_sandbox.ipynb"

    for path in (tour, crouter):
        code = _join_code_cells(path)
        # The tour notebooks should ALWAYS load prebuilt agents via the
        # bundled default registry.
        assert "AgentRegistry.default()" in code, (
            f"{path.name} must call AgentRegistry.default() to reach bundled agents"
        )
        # Empty-arg construction of AgentRegistry is the footgun — it
        # builds an empty registry whose .get() returns None.
        assert "AgentRegistry()" not in code, (
            f"{path.name} should not use AgentRegistry() — default() loads "
            f"the bundled agents.json"
        )
        # AgentDefinition uses snake_case — never camelCase.
        assert ".maxIterations" not in code, (
            f"{path.name} references AgentDefinition.maxIterations — "
            f"the real field name is `max_iterations`"
        )
