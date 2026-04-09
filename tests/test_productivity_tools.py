from pathlib import Path

from shipit_agent import (
    ArtifactBuilderTool,
    DecisionMatrixTool,
    EvidenceSynthesisTool,
    PlannerTool,
    PromptTool,
    ThoughtDecompositionTool,
    ToolSearchTool,
    VerifierTool,
)


def test_prompt_tool_builds_prompt_text() -> None:
    tool = PromptTool()
    result = tool.run(
        context=None,  # type: ignore[arg-type]
        goal="Be a cybersecurity analyst",
        constraints=["Be concise", "Use bullet points"],
        style="Professional",
    )
    assert "cybersecurity analyst" in result.text
    assert "Constraints:" in result.text


def test_verifier_tool_detects_missing_criteria() -> None:
    tool = VerifierTool()
    result = tool.run(
        context=None,  # type: ignore[arg-type]
        content="hello world",
        criteria=["hello", "goodbye"],
    )
    assert result.metadata["passed"] is False


def test_artifact_builder_stores_artifact() -> None:
    tool = ArtifactBuilderTool()
    context = type("Ctx", (), {"state": {}})()
    result = tool.run(context=context, name="report.md", content="# report")
    assert result.metadata["artifact"]["name"] == "report.md"
    assert context.state["artifacts"][0]["name"] == "report.md"


def test_artifact_builder_can_export_to_file(tmp_path: Path) -> None:
    tool = ArtifactBuilderTool(workspace_root=tmp_path)
    context = type("Ctx", (), {"state": {"artifact_workspace_root": str(tmp_path)}})()
    result = tool.run(
        context=context,
        name="report.md",
        content="# report",
        export=True,
        path="exports/report.md",
    )
    exported_path = Path(result.metadata["artifact"]["path"])
    assert exported_path.exists()
    assert exported_path.read_text(encoding="utf-8") == "# report"


def test_planner_tool_returns_ordered_plan() -> None:
    tool = PlannerTool()
    result = tool.run(context=None, goal="Ship a release")  # type: ignore[arg-type]
    assert "1." in result.text
    assert "Goal:" in result.text


def test_tool_search_can_find_available_tools() -> None:
    tool = ToolSearchTool()
    result = tool.run(
        context=type("Ctx", (), {"state": {"available_tools": [{"name": "web_search", "description": "Search the web", "prompt_instructions": ""}]}})(),
        query="search web",
    )
    assert "web_search" in result.text


def test_thought_decomposition_tool_returns_structure() -> None:
    tool = ThoughtDecompositionTool()
    result = tool.run(context=None, problem="Migrate a large project", objective="Ship safely")  # type: ignore[arg-type]
    assert "Workstreams:" in result.text
    assert "Risks:" in result.text


def test_evidence_synthesis_tool_returns_grounded_sections() -> None:
    tool = EvidenceSynthesisTool()
    result = tool.run(
        context=None,  # type: ignore[arg-type]
        observations=["Build is failing in CI", "Local tests pass", "Dependency version changed"],
        question="Why is CI failing?",
    )
    assert "Facts:" in result.text
    assert "Recommendations:" in result.text


def test_decision_matrix_tool_recommends_first_option() -> None:
    tool = DecisionMatrixTool()
    result = tool.run(
        context=None,  # type: ignore[arg-type]
        decision="Choose a deployment path",
        options=["Blue/green", "Rolling"],
        criteria=["safety", "speed"],
    )
    assert "Recommendation: Blue/green" in result.text
    assert result.metadata["fallback"] == "Rolling"
