"""`notebook_edit` — read and edit Jupyter notebooks cell by cell.

Works on the public nbformat-4 JSON structure. Actions:

- ``list``            — numbered cell index (type + first line + exec count)
- ``read``            — one cell's full source (and text outputs)
- ``edit``            — replace a cell's source
- ``add``             — insert a new cell at an index (or append)
- ``delete``          — remove a cell
- ``clear_outputs``   — strip all outputs/execution counts

Edits preserve every other field (metadata, ids, outputs of untouched
cells) — the file is loaded as JSON, modified minimally, and written back
with nbformat-friendly indentation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


class NotebookEditTool:
    name = "notebook_edit"
    description = (
        "Read, edit, add, or delete cells in a Jupyter notebook (.ipynb)."
    )

    def __init__(self, *, root_dir: str | Path = "/tmp") -> None:
        self.root_dir = Path(root_dir).resolve()
        self.prompt = self.prompt_instructions = (
            "Use for .ipynb files instead of edit_file — it edits cells "
            "structurally. Always `list` first, then `read` the target cell, "
            "then `edit` with the full new source."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Notebook path"},
                        "action": {
                            "type": "string",
                            "enum": ["list", "read", "edit", "add", "delete",
                                     "clear_outputs"],
                        },
                        "index": {
                            "type": "integer",
                            "description": "Cell index (list shows them)",
                        },
                        "source": {
                            "type": "string",
                            "description": "New cell source (edit/add)",
                        },
                        "cell_type": {
                            "type": "string",
                            "enum": ["code", "markdown"],
                            "description": "Cell type for `add` (default code)",
                        },
                    },
                    "required": ["path", "action"],
                },
            },
        }

    # ------------------------------------------------------------------
    def _resolve(self, raw: str) -> Path:
        candidate = Path(raw)
        candidate = (candidate if candidate.is_absolute()
                     else self.root_dir / candidate).resolve()
        if not candidate.is_relative_to(self.root_dir):
            raise ValueError(f"Path escapes project root: {candidate}")
        return candidate

    @staticmethod
    def _source_text(cell: dict[str, Any]) -> str:
        src = cell.get("source", "")
        return "".join(src) if isinstance(src, list) else str(src)

    @staticmethod
    def _first_line(cell: dict[str, Any]) -> str:
        text = NotebookEditTool._source_text(cell).strip()
        return text.splitlines()[0][:70] if text else "(empty)"

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        try:
            path = self._resolve(str(kwargs.get("path", "")))
        except ValueError as exc:
            return ToolOutput(text=str(exc), metadata={"ok": False})
        action = str(kwargs.get("action", "list"))

        if not path.exists():
            return ToolOutput(text=f"Notebook not found: {path}",
                              metadata={"ok": False})
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
            cells = nb["cells"]
        except (json.JSONDecodeError, KeyError) as exc:
            return ToolOutput(text=f"Not a valid notebook: {exc}",
                              metadata={"ok": False})

        index = kwargs.get("index")

        if action == "list":
            lines = [f"{path.name} — {len(cells)} cells"]
            for i, cell in enumerate(cells):
                exec_count = cell.get("execution_count")
                marker = f"[{exec_count}]" if exec_count is not None else "[ ]"
                lines.append(
                    f"{i:>3} {cell.get('cell_type', '?'):<9} {marker:<5} "
                    f"{self._first_line(cell)}"
                )
            return ToolOutput(text="\n".join(lines),
                              metadata={"ok": True, "cells": len(cells)})

        if action in ("read", "edit", "delete") and (
            index is None or not 0 <= int(index) < len(cells)
        ):
            return ToolOutput(
                text=f"Invalid index {index!r} — notebook has {len(cells)} "
                     "cells (use action=list).",
                metadata={"ok": False},
            )

        if action == "read":
            cell = cells[int(index)]
            body = self._source_text(cell)
            outputs = [
                "".join(o.get("text", []))
                for o in cell.get("outputs", [])
                if o.get("output_type") in ("stream", "execute_result")
            ]
            text = f"cell {index} ({cell.get('cell_type')}):\n{body}"
            if any(o.strip() for o in outputs):
                text += "\n--- outputs ---\n" + "\n".join(outputs)[:2000]
            return ToolOutput(text=text, metadata={"ok": True})

        # Mutating actions from here on.
        if action == "edit":
            cells[int(index)]["source"] = str(kwargs.get("source", ""))
            summary = f"cell {index} replaced"
        elif action == "add":
            new_cell: dict[str, Any] = {
                "cell_type": str(kwargs.get("cell_type", "code")),
                "metadata": {},
                "source": str(kwargs.get("source", "")),
            }
            if new_cell["cell_type"] == "code":
                new_cell["execution_count"] = None
                new_cell["outputs"] = []
            at = len(cells) if index is None else max(0, min(int(index), len(cells)))
            cells.insert(at, new_cell)
            summary = f"cell inserted at {at}"
        elif action == "delete":
            cells.pop(int(index))
            summary = f"cell {index} deleted"
        elif action == "clear_outputs":
            for cell in cells:
                if cell.get("cell_type") == "code":
                    cell["outputs"] = []
                    cell["execution_count"] = None
            summary = "all outputs cleared"
        else:
            return ToolOutput(text=f"Unknown action '{action}'.",
                              metadata={"ok": False})

        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return ToolOutput(
            text=f"{path.name}: {summary} ({len(cells)} cells now)",
            metadata={"ok": True, "path": str(path), "cells": len(cells)},
        )
