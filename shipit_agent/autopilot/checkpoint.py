"""Atomic checkpoint read/write for the Autopilot."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .budget import BudgetUsage


class CheckpointStore:
    """File-per-run JSON checkpoint store with atomic swaps.

    A crash during save cannot corrupt an existing checkpoint — we write
    to ``<run_id>.json.tmp`` first and ``replace()`` to swap it in.
    """

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory).expanduser()

    def path(self, run_id: str) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory / f"{run_id}.json"

    def exists(self, run_id: str) -> bool:
        return self.path(run_id).exists()

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.path(run_id)
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def save(
        self,
        run_id: str,
        *,
        goal: dict[str, Any],
        usage: BudgetUsage,
        step_outputs: list[dict[str, Any]],
        output: str,
    ) -> None:
        payload = {
            "run_id": run_id,
            "goal": goal,
            "iterations": usage.iterations,
            "usage": usage.to_dict(),
            "step_outputs": step_outputs,
            "output": output,
            "saved_at": time.time(),
        }
        target = self.path(run_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(target)
