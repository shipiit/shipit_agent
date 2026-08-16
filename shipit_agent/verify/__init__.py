"""Verification ledger — gate an agent's "done" on test evidence, not its word.

An edit marks the workspace dirty; only a matching test/build that exits 0 marks
it clean. The loop then refuses to finish a turn that changed code without fresh
passing evidence — the spine of an autonomous coding agent that doesn't ship
broken code.

    from shipit_agent.verify import VerificationLedger, detect_verify_commands
    from shipit_agent.verify.gate import build_verify_nudge, classify_command

    ledger = VerificationLedger(".shipit/verify.db")
    ledger.mark_edited(session_id=sid, root=".", paths=["app.py"])
    ledger.record_run(session_id=sid, root=".", command="pytest", passed=False, summary="1 failed")
    ledger.status(session_id=sid, root=".").status      # -> "unverified"

The library is standalone and fully tested; wiring it into the runtime loop
(mark on edit, record on a verify run, gate the final answer) is the caller's
thin call site — see `gate.py`.
"""

from .gate import (
    any_verifiable,
    build_verify_nudge,
    classify_command,
    is_verifiable_path,
)
from .ledger import VerificationLedger, VerificationStatus
from .project_facts import detect_verify_commands

__all__ = [
    "VerificationLedger",
    "VerificationStatus",
    "any_verifiable",
    "build_verify_nudge",
    "classify_command",
    "detect_verify_commands",
    "is_verifiable_path",
]
