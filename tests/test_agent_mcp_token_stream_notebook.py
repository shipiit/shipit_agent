from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "78_agent_mcp_token_stream_audit.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_notebook_covers_agent_mcp_streaming_and_token_audit() -> None:
    notebook = _load_notebook()
    source = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )

    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) >= 20
    for marker in (
        "bedrock-mantle/google.gemma-4-26b-a4b",
        "MCPStreamableHTTPTransport",
        "tool_meta_resolver",
        "include_server_in_tool_names",
        "agent.stream(TASK)",
        "tool_output_delta",
        "model_output_chars",
        "cache_read_input_tokens",
        "run_failed",
        "large_result_complete",
        "no_unrelated_skill_injection",
        "skills_selected",
    ):
        assert marker in source


def test_every_notebook_code_cell_compiles() -> None:
    notebook = _load_notebook()

    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") != "code":
            continue
        ast.parse(
            "".join(cell.get("source", [])),
            filename=f"{NOTEBOOK}:cell-{index}",
        )


def test_notebook_offers_raw_events_and_a_compact_progress_transcript() -> None:
    notebook = _load_notebook()
    sources = [
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    ]
    assert any("print('event', repr(event))" in source for source in sources)
    assert any("progress_transcript" in source for source in sources)
