"""audit-log plugin — record every tool call.

Attaches an ``after_tool`` hook that appends one line per tool call to an audit
file (``$SHIPIT_AUDIT_LOG`` or ``./shipit-audit.log``). A hook that only
observes returns ``None``, so it never alters a tool's result — a clean example
of the observe-only side of the hook contract.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _audit_path() -> str:
    return os.getenv("SHIPIT_AUDIT_LOG", "shipit-audit.log")


def register(reg: Any) -> None:
    def after_tool(name: str, result: Any) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()}\t{name}\n"
        try:
            with open(_audit_path(), "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            # Auditing must never break a run — but a failed write is surfaced
            # (a warning), never swallowed, so a broken audit path is visible.
            logger.warning("audit-log: could not write %s: %s", _audit_path(), exc)
        return None  # observe-only: do not modify the tool result

    reg.add_hook("after_tool", after_tool)
