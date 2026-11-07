"""How the tree view draws each transcript row: work, calls, cards and the footer."""

from __future__ import annotations

import os
import textwrap
from typing import Any

from .grouping import ApprovalRow, ArtifactRow, ConnectionRow, DecisionRow, NoticeRow, ProseRow, SubAgentRow, WorkRow

# Where a call's status sits, so statuses line up down the page.
_STATUS_COLUMN = 52


def _terminal_width(default: int = 100) -> int:
    try:
        return max(60, os.get_terminal_size().columns)
    except OSError:
        return default


def _visible_length(text: str) -> int:
    """Length ignoring ANSI escape sequences."""
    import re

    return len(re.sub(r"\033\[[0-9;]*m", "", text))


class TreeRowsMixin:
    """The row-by-row drawing of :class:`~shipit_agent.narrate.tree.TreeRenderer`."""

    def _render_row(
        self,
        row: Any,
        branch: str,
        trunk: str,
        *,
        is_answer: bool,
        is_opening: bool = False,
    ) -> list[str]:
        if isinstance(row, ProseRow):
            if is_answer:
                title = "Final answer"
            elif is_opening:
                title = "Understanding request"
            else:
                title = "Decision"
            colour = "bold" if is_answer else "accent"
            lines = [f"{branch} {self._c(colour, title)}"]
            lines += [f"{trunk}{line}" for line in self._wrap(row.text, len(trunk))]
            return lines

        if isinstance(row, DecisionRow):
            lines = [f"{branch} {self._c('accent', row.label)}"]
            lines += [f"{trunk}{line}" for line in self._wrap(row.text, len(trunk))]
            return lines

        if isinstance(row, WorkRow):
            group = row.group
            lines = [f"{branch} {self._c('bold', 'Tool group')}: {group.label}"]
            lines += self._call_block(group.calls, trunk)
            return lines

        if isinstance(row, SubAgentRow):
            lines = [
                f"{branch} {self._c('bold', 'Delegated')}: "
                f"{self._c('dim', row.task[:60])}"
            ]
            lines += self._call_block(row.calls, trunk)
            return lines

        if isinstance(row, ApprovalRow):
            state = "auto-approved" if row.auto_approved else "awaiting approval"
            lines = [f"{branch} {self._c('accent', 'Approval required')}"]
            lines.append(
                f"{trunk}{self._pad(row.title, row.tag or state, prefix=len(trunk))}"
            )
            return lines

        if isinstance(row, ArtifactRow):
            return [
                f"{branch} {self._c('bold', 'Artifact')}: {row.title or row.name}",
                f"{trunk}{self._c('dim', f'{row.kind} · {row.path}')}",
            ]

        if isinstance(row, ConnectionRow):
            lines = [f"{branch} {self._c('accent', 'Connection needed')}"]
            lines.append(
                f"{trunk}{self._pad(row.title, row.auth, prefix=len(trunk))}"
            )
            if row.reason:
                lines += [
                    f"{trunk}{line}"
                    for line in self._wrap(row.reason, len(trunk))
                ]
            return lines

        if isinstance(row, NoticeRow):
            return [
                f"{branch} {self._c('bold', 'Note')}",
                f"{trunk}{self._c('dim', row.text)}",
            ]
        return []

    def _call_block(self, calls: list[Any], trunk: str) -> list[str]:
        """Every call in a group, one branch each.

        In ``detail`` mode each branch carries what it was *called with* and
        what came *back* — the two things you actually need when a run did
        something you did not expect.
        """
        lines: list[str] = []
        prefix = len(trunk) + len(self._tee) + 1
        for position, call in enumerate(calls):
            last = position == len(calls) - 1
            inner = self._corner if last else self._tee
            lines.append(f"{trunk}{inner} {self._call_line(call, prefix)}")
            if self._detail:
                # Continuation sits under this branch, not beside the next one.
                lines += [
                    f"{trunk}{'   ' if last else f'{self._pipe}  '}{line}"
                    for line in self._detail_lines(call)
                ]
        return lines

    def _detail_lines(self, call: Any) -> list[str]:
        lines: list[str] = []
        arguments = getattr(call, "arguments", None) or {}
        if arguments:
            rendered = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
            lines.append(self._c("dim", f"↳ {rendered[:160]}"))
        # Dedented, not stripped: stripping would pull the *first* line flush
        # left and leave the rest indented, which reads as broken output.
        body = textwrap.dedent(
            getattr(call, "error", "") or getattr(call, "output", "")
        ).strip("\n")
        if body:
            # `output_lines=None` means every line — a tree you can read the
            # whole run out of, at the cost of its compactness.
            shown = (
                body.splitlines()
                if self._output_lines is None
                else body.splitlines()[: self._output_lines]
            )
            lines += [self._c("dim", f"  {line[:120]}") for line in shown]
            hidden = len(body.splitlines()) - len(shown)
            if hidden > 0:
                lines.append(self._c("dim", f"  … {hidden} more lines"))
        return lines

    def _call_line(self, call: Any, prefix: int = 0) -> str:
        status = {
            "ok": self._c("green", "completed"),
            "error": self._c("red", "failed"),
            "denied": self._c("red", "blocked"),
            "running": self._c("dim", "running"),
        }.get(call.status, call.status)
        duration = f"{call.duration_ms:.0f}ms" if call.duration_ms else ""
        right = f"{status}  {self._c('dim', duration)}" if duration else status
        return self._pad(call.name, right, prefix=prefix)

    def _pad(self, left: str, right: str, *, prefix: int = 0) -> str:
        """Left text, then *right* aligned at a fixed column.

        ``prefix`` is the width of the tree drawing already on the line. A row
        nested two levels deep starts further right, so without it the status
        column drifts and the whole point of a fixed column is lost.

        Padding is computed on the *visible* width, since ANSI codes would
        otherwise push every coloured status a few characters out of line.
        """
        if not _visible_length(right):
            return left
        gap = max(1, _STATUS_COLUMN - prefix - _visible_length(left))
        return f"{left}{' ' * gap}{right}"

    def _wrap(self, text: str, indent: int) -> list[str]:
        width = max(30, _terminal_width() - indent - 2)
        out: list[str] = []
        for paragraph in text.strip().splitlines():
            out.extend(textwrap.wrap(paragraph, width=width) or [""])
        return out

    def _footer(self) -> str:
        usage = self._acc.usage or {}
        tokens = int(usage.get("total_tokens") or 0) or (
            int(usage.get("prompt_tokens") or 0)
            + int(usage.get("completion_tokens") or 0)
        )
        parts = [f"{tokens:,} tokens"] if tokens else []
        if self._model:
            parts.append(self._model)
        return self._c("dim", " · ".join(parts)) if parts else ""
