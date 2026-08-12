from __future__ import annotations

import ast
import json
from pathlib import Path


NOTEBOOK = (
    Path(__file__).resolve().parents[1]
    / "notebooks"
    / "79_advanced_real_agent_sdk_live_audit.ipynb"
)


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_every_live_scenario_uses_the_event_stream() -> None:
    source = "\n".join(
        "".join(cell.get("source", [])) for cell in _notebook()["cells"]
    )

    assert "for event in agent.stream(prompt)" in source
    for agent_name in (
        "simple_agent",
        "research_agent",
        "coding_agent",
        "mixed_agent",
        "deep_agent",
        "candidate_agent",
    ):
        assert f"{agent_name}.run(" not in source
    for label in (
        "dormant catalog",
        "deferred MCP research",
        "coding repair",
        "mixed local and MCP evidence",
        "DeepAgent contract",
        "model matrix",
    ):
        assert label in source
    for event_type in (
        "text_delta",
        "tool_context",
        "run_completed",
    ):
        assert event_type in source


def test_notebook_json_and_code_cells_are_valid() -> None:
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") == "code":
            ast.parse(
                "".join(cell.get("source", [])),
                filename=f"{NOTEBOOK}:cell-{index}",
            )
