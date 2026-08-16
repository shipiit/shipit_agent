"""The verify-on-stop gate — the runtime's thin call site over the ledger.

This is what turns the standalone verification ledger (:mod:`.ledger`) into a
loop behaviour: as tools run it records edits and verify runs, and when the model
tries to finish a turn it can refuse — returning a nudge to run the tests — if
code changed this turn without fresh passing evidence.

Kept out of the runtime module so it stays independently testable: the runtime
feeds it three facts per tool (was it read-only, what paths did it declare, and —
for a shell command — what ran and with what exit code) and asks one question at
the finish line (:meth:`stop_nudge`). All the policy lives here.
"""

from __future__ import annotations

from pathlib import Path

from .gate import build_verify_nudge, classify_command, is_verifiable_path
from .ledger import VerificationLedger
from .project_facts import detect_verify_commands


class VerifyGate:
    """Per-run edit/verify tracking + the stop decision, over one ledger."""

    def __init__(
        self,
        *,
        session_id: str,
        root: str | Path,
        db_path: str | Path = ":memory:",
        max_attempts: int = 2,
    ) -> None:
        self.session_id = str(session_id or "")
        self.root = str(Path(root).expanduser())
        self.ledger = VerificationLedger(db_path)
        #: The project's verify commands, sniffed once. Empty → the gate is a
        #: no-op (nothing to verify against), so a non-code project is unaffected.
        self.commands = detect_verify_commands(self.root)
        #: Did *this run* edit code a test could cover? The stop guard only fires
        #: when it did — a read-only or docs-only turn never demands a test run.
        self.edited_this_turn = False
        #: Bounded so a wedged verify loop can't trap the run.
        self.max_attempts = max_attempts
        self._attempts = 0

    def note_tool(
        self,
        *,
        read_only: bool,
        paths: list[str] | None = None,
        command: str = "",
        exit_code: int | None = None,
        output: str = "",
        ok: bool | None = None,
    ) -> None:
        """Fold one finished tool call into the ledger.

        - A **non-read-only** tool that touched a **verifiable** path dirties the
          workspace (an edit) — a README-only change never does, and a **failed**
          tool (``ok is False``) never does either: a rejected edit didn't land,
          so demanding tests for it would be a phantom.
        - A shell **command matching a project verify command** records pass/fail
          by its real **exit code** — the evidence the stop guard reads.
        """
        if not read_only and paths and ok is not False:
            verifiable = [p for p in paths if is_verifiable_path(p)]
            if verifiable:
                self.ledger.mark_edited(
                    session_id=self.session_id, root=self.root, paths=verifiable
                )
                self.edited_this_turn = True

        if command and exit_code is not None and classify_command(command, self.commands):
            self.ledger.record_run(
                session_id=self.session_id,
                root=self.root,
                command=command,
                passed=int(exit_code) == 0,
                summary=(output or "").strip()[-1500:],
            )

    def would_nudge(self) -> bool:
        """Would the turn be sent back to verify? A non-consuming check.

        Unlike :meth:`stop_nudge` this ignores the attempt cap and never mutates
        state — the loop uses it to notice an edited-but-unverified turn that ran
        out of steps, so a silent unverified "done" can still be surfaced.
        """
        if not self.commands or not self.edited_this_turn:
            return False
        return self.ledger.status(
            session_id=self.session_id, root=self.root
        ).status != "passed"

    def stop_nudge(self) -> str | None:
        """A "run the tests before you finish" nudge, or ``None`` to let it stop.

        Returns a nudge only when: the project has verify commands, this run
        edited code, there's no fresh *passing* evidence, and we haven't already
        nudged ``max_attempts`` times. Otherwise ``None`` — the turn finishes.
        """
        if self._attempts >= self.max_attempts:
            return None
        if not self.would_nudge():
            return None
        status = self.ledger.status(session_id=self.session_id, root=self.root)
        self._attempts += 1
        return build_verify_nudge(status, self.commands)

    @staticmethod
    def project_root_from_output_dir(tool_output_dir: str) -> str:
        """Best-effort project root from the runtime's ``.shipit/...`` output dir.

        ``tool_output_dir`` is ``<root>/.shipit/tool-results``; the root is two
        levels up. Falls back to the current directory when it isn't set.
        """
        if not tool_output_dir:
            return "."
        path = Path(tool_output_dir)
        for parent in path.parents:
            if parent.name == ".shipit":
                return str(parent.parent)
        return str(path)
