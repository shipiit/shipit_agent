from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "77_super_agent_live_validation.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK.read_text())


def test_super_agent_notebook_has_complete_validation_surface() -> None:
    notebook = _load_notebook()
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) >= 17
    for required in (
        "Agent.for_project",
        "optimized=True",
        "ToolOutputChunk",
        "tool_output_delta",
        "PermissionEngine",
        "MCPServer",
        "cache_read_input_tokens",
        "chat_session",
        "MediaParser",
        "build_multimodal_message",
        "configured_llm",
        "RUN_LIVE",
        "Deep live read-only architecture audit",
        "Live isolated edit-and-verify challenge",
    ):
        assert required in source


def test_every_notebook_code_cell_compiles() -> None:
    notebook = _load_notebook()
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        compile(source, f"{NOTEBOOK.name}:cell-{index}", "exec")


def test_ci_tagged_notebook_cells_execute_end_to_end(monkeypatch) -> None:
    notebook = _load_notebook()
    namespace = {"__name__": "__notebook_test__"}
    monkeypatch.chdir(ROOT)

    for index, cell in enumerate(notebook["cells"]):
        if "ci" not in cell.get("metadata", {}).get("tags", []):
            continue
        source = "".join(cell["source"])
        exec(compile(source, f"{NOTEBOOK.name}:cell-{index}", "exec"), namespace)

    events = namespace["events"]
    assert namespace["agent"].code_mode is True
    assert any(event.type == "tool_output_delta" for event in events)
    assert namespace["media_message"]["content"][1]["type"] == "image"
