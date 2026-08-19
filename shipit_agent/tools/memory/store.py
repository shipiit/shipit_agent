"""Facts that outlive a run, as a small JSON file."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

logger = logging.getLogger(__name__)

__all__ = ["MemoryStore"]


@dataclass
class MemoryStore:
    """Keyed facts, deliberately minimal.

    A memory that stores everything becomes noise the model reads past on every
    run, so this holds only what a person or the model chose to keep. Nothing
    implicit is captured.
    """

    path: Path | None = None
    items: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path).expanduser()
            self.load()

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt memory file must not stop a run starting.
            logger.warning("Ignoring unreadable memory file %s", self.path)
            return
        if isinstance(data, Mapping):
            self.items = {str(k): str(v) for k, v in data.items()}

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.items, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError as error:
            logger.warning("Could not write memory to %s: %s", self.path, error)
