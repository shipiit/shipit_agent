"""How the live chat panel draws each transcript row as HTML."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .grouping import ApprovalRow, ArtifactRow, CallRecord, ConnectionRow, DecisionRow, NoticeRow, ProseRow, SubAgentRow, WorkRow


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _clip(text: str, limit: int | None) -> str:
    """Trim to *limit*, or not at all when it is ``None``.

    ``output_limit=None`` means "show me everything" — the panel scrolls each
    output in its own box, so a long file costs height in that box rather
    than in the page.
    """
    text = text.strip()
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class LiveViewHtmlMixin:
    """The row-by-row HTML of :class:`~shipit_agent.narrate.live_ui.LiveView`."""

    def _tree_html(self) -> str:
        """The compact tree, redrawn each tick, inside the same card.

        It shares this view's accumulator, so the tree and the chat shape are
        two readings of one run rather than two runs of the same events.
        """
        from .tree import TreeRenderer

        renderer = TreeRenderer(
            color=False,
            live=False,
            show_footer=False,
            # Compact by design: the tree is the *shape* of the run. For
            # arguments and output, render_tree(..., detail=True).
            detail=False,
            accumulator=self._acc,
        )
        return f'<pre class="sa-tree">{_esc(renderer.render(live=not self._done))}</pre>'

    def _row_html(self, row: Any, *, streaming: bool = False) -> str:
        if isinstance(row, ProseRow):
            caret = '<span class="sa-caret"></span>' if streaming else ""
            return f'<div class="sa-prose">{_esc(row.text)}{caret}</div>'

        if isinstance(row, DecisionRow):
            return (
                f'<div class="sa-decision sa-{_esc(row.kind)}">'
                f'<span class="sa-step">{_esc(row.label)}</span>'
                f"{_esc(row.text)}</div>"
            )

        if isinstance(row, WorkRow):
            return self._work_html(row.group.icon, row.group.label, row.group.calls)

        if isinstance(row, SubAgentRow):
            inner = self._work_html("↳", f"{row.agent} · {row.label}", row.calls)
            return f'<div class="sa-sub">{inner}</div>'

        if isinstance(row, ApprovalRow):
            return self._approval_html(row)

        if isinstance(row, ConnectionRow):
            return self._connection_html(row)

        if isinstance(row, ArtifactRow):
            return self._artifact_html(row)

        if isinstance(row, NoticeRow):
            return f'<div class="sa-notice">{_esc(row.text)}</div>'
        return ""

    def _work_html(self, icon: str, label: str, calls: list[CallRecord]) -> str:
        running = any(call.status == "running" for call in calls)
        failed = any(call.status in ("error", "denied") for call in calls)
        klass = "sa-row" + (" sa-run" if running else "") + (" sa-err" if failed else "")

        targets = []
        seen: set[str] = set()
        for call in calls:
            target = call.target
            if target and target not in seen:
                seen.add(target)
                targets.append(target)
        detail = (
            f'<div class="sa-targets">{_esc(" · ".join(targets))}</div>'
            if targets
            else ""
        )
        # The right-hand meta, as the reference UI shows it: how many calls
        # this row stands for, and how long they took together.
        elapsed = sum(call.duration_ms for call in calls)
        meta = f"{len(calls)} tool{'s' if len(calls) != 1 else ''}"
        if elapsed:
            meta += f" · {elapsed:.1f}ms" if elapsed < 100 else f" · {elapsed:.0f}ms"
        return (
            f'<div class="{klass}">'
            f'<span class="sa-glyph">{_esc(icon)}</span>'
            f'<span class="sa-label"><b>{_esc(label)}</b>'
            f'{" ›" if not running else " …"}{detail}'
            f'{"".join(self._call_html(call) for call in calls)}'
            f'</span><span class="sa-count">{_esc(meta)}</span></div>'
        )

    def _call_html(self, call: CallRecord) -> str:
        """One call, folded away — open it to see exactly what came back.

        This is the part a screenshot cannot give you: the *real* output of
        the *real* call, not a summary of it.
        """
        if not self.show_output or call.status == "running":
            return ""
        body = call.error or call.output
        if not body:
            return ""
        mark = "✗" if call.status in ("error", "denied") else "✓"
        timing = f" · {call.duration_ms:.0f}ms" if call.duration_ms else ""
        return (
            f'<details class="sa-call"><summary>{mark} {_esc(call.name)}{timing} '
            f"— {len(body.splitlines())} lines</summary>"
            f'<pre class="sa-out">{_esc(_clip(body, self.output_limit))}</pre>'
            f"</details>"
        )

    def _approval_html(self, row: ApprovalRow) -> str:
        state = "auto-approved" if row.auto_approved else "waiting on you"
        meta = " · ".join(
            part for part in (f"#{row.action_id}", row.tag, row.tool, state) if part
        )
        choices = (
            ""
            if row.auto_approved
            else (
                '<div class="sa-choices"><span>Always approve</span>'
                "<span>Deny</span>"
                '<span class="sa-primary">Approve</span></div>'
            )
        )
        return (
            f'<div class="sa-approval">'
            f'<div class="sa-what"><span class="sa-bullet">●</span>'
            f"{_esc(row.title)}</div>"
            f'<div class="sa-meta">{_esc(meta)}</div>'
            f"{choices}</div>"
        )

    def _artifact_html(self, row: ArtifactRow) -> str:
        """`Q2 Kickoff Brief · Doc · Click to open` — the thing you keep.

        The link is a plain ``file://`` URL: no server, no viewer, nothing to
        install. In a notebook it opens the file; in a page you would swap it
        for whatever your app routes to.
        """
        glyph = {
            "Page": "◍", "Doc": "▤", "Sheet": "⊞", "Data": "⛁",
            "Image": "◫", "Deck": "▧", "Code": "❯", "PDF": "▤",
            "Archive": "▩",
        }.get(row.kind, "▤")
        href = Path(row.path).resolve().as_uri() if row.path else ""
        return (
            f'<a class="sa-artifact" href="{_esc(href)}" target="_blank">'
            f'<span class="sa-file">{glyph}</span>'
            f'<span class="sa-art-body"><b>{_esc(row.title or row.name)}</b>'
            f'<span class="sa-art-meta">{_esc(row.kind)} · Click to open</span>'
            f"</span><span class=\"sa-open\">↗</span></a>"
        )

    def _connection_html(self, row: ConnectionRow) -> str:
        """`BigQuery — analytics.usage · Connect` — the ask, and the reason.

        The reason is the whole card: a user deciding whether to hand over an
        account is answering *why*, not *what*.
        """
        how = {
            "oauth": "sign in",
            "api_key": "paste an API key",
            "token": "paste a token",
        }.get(row.auth, "connect it")
        return (
            f'<div class="sa-connect">'
            f'<div class="sa-what"><span class="sa-plug">⚯</span>'
            f"{_esc(row.title)}</div>"
            f'<div class="sa-reason">{_esc(row.reason)}</div>'
            f'<div class="sa-meta">{_esc(row.connection_id)} · {_esc(how)}</div>'
            f'<div class="sa-choices"><span>Not now</span>'
            f'<span class="sa-primary">Connect</span></div>'
            f"</div>"
        )

    def _footer(self) -> str:
        usage = self._acc.usage or {}
        tokens = int(usage.get("total_tokens") or 0) or (
            int(usage.get("prompt_tokens") or 0)
            + int(usage.get("completion_tokens") or 0)
        )
        parts: list[str] = []
        if tokens:
            parts.append(f"{tokens:,} tokens")
        if self.cost_usd is not None:
            parts.append(f"${self.cost_usd:,.2f}")
        if self.model:
            parts.append(self.model)
        return _esc(" · ".join(parts))
