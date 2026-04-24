"""Atomic checkpoint read/write for the Autopilot.

A 24-hour Autopilot run can outlive its host process — VM reboots, oom
kills, systemd restarts, a laptop lid closing. The checkpoint store is
the only durable state that bridges those restarts, so it has to be:

  * **Atomic**: we write ``<run_id>.json.tmp`` and ``replace()`` it in,
    so a crash during save can never leave a half-written file.
  * **Forensic on corruption**: a JSON parse error doesn't silently
    reset the run — we move the bad file aside as
    ``<run_id>.corrupted.<ts>.json`` so an operator can inspect it.
  * **Complete**: every field the run needs to resume cumulatively is
    written, including the full :class:`BudgetUsage` (not just the
    iteration count). Without this, a resume after a 12-hour crash
    would forget the 12 hours already spent.
"""

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
        """Read the checkpoint payload. Returns ``{}`` for missing OR
        unreadable files.

        On JSON corruption the bad file is quarantined (renamed to
        ``<run_id>.corrupted.<ts>.json``) so an operator can inspect it
        later — silently returning ``{}`` would reset a multi-hour run.
        """
        path = self.path(run_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            quarantine = path.with_suffix(f".corrupted.{int(time.time())}.json")
            try:
                path.replace(quarantine)
            except OSError:
                pass
            return {}
        except OSError:
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
            # `iterations` kept at top level for backwards-compat with
            # any earlier reader; the authoritative totals are in `usage`.
            "iterations": usage.iterations,
            "usage": usage.to_dict(),
            "step_outputs": step_outputs,
            "output": output,
            "saved_at": time.time(),
            "schema_version": 2,
        }
        target = self.path(run_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(target)

    @staticmethod
    def usage_from_payload(prior: dict[str, Any]) -> BudgetUsage:
        """Reconstruct a :class:`BudgetUsage` from a loaded checkpoint.

        Tolerates both schema v1 (iterations-only) and schema v2 (full
        usage dict) so older checkpoints keep working after upgrade.
        """
        raw = prior.get("usage") or {}
        return BudgetUsage(
            seconds=float(raw.get("seconds", 0.0) or 0.0),
            tool_calls=int(raw.get("tool_calls", 0) or 0),
            tokens=int(raw.get("tokens", 0) or 0),
            dollars=float(raw.get("dollars", 0.0) or 0.0),
            iterations=int(prior.get("iterations", raw.get("iterations", 0)) or 0),
        )
