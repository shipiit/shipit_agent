"""The run as a live chat panel — for notebooks.

:class:`~shipit_agent.narrate.renderer.NarratorRenderer` is the terminal view
and :mod:`~shipit_agent.narrate.share` is the file you email someone. This is
the third surface: an HTML card that **redraws in place** inside a Jupyter
output cell while the agent is still working, so you watch tokens land, tool
rows appear and settle, and approval cards interrupt the flow::

    from shipit_agent.narrate.live_ui import watch

    answer = watch(agent, "Which accounts are at risk this quarter?")

Nothing here is presentation-only trickery over a finished run: it is fed the
same :class:`~shipit_agent.narrate.grouping.WorkRunAccumulator` as every other
renderer, so a row reads identically in the terminal, in the shared HTML file
and here. Only the shape changes.

Two deliberate constraints:

- **Every selector is scoped under ``.sa-live``.** Notebook output shares one
  document with the whole page; a bare ``body {…}`` rule here would restyle
  the user's notebook.
- **Redraws are throttled.** A full re-render per token is O(n²) DOM churn and
  stutters exactly when the answer gets long, which is the opposite of what a
  live view is for. Structural events (a call starting, an approval landing,
  the run finishing) always flush immediately; token deltas flush on a time
  budget.
"""

from __future__ import annotations

import html
import time
from typing import Any, Iterable

from shipit_agent.models import AgentEvent

from .grouping import (
    ApprovalRow,
    CallRecord,
    NoticeRow,
    ProseRow,
    SubAgentRow,
    WorkRow,
    WorkRunAccumulator,
)

__all__ = ["LiveView", "render_chat_html", "watch", "watch_tree"]

# Events that change the *structure* of the panel rather than extend a line of
# prose. Nobody should wait 50ms to learn that a tool started.
_STRUCTURAL = frozenset(
    {
        "tool_called",
        "tool_completed",
        "tool_failed",
        "tool_denied",
        "action_queued",
        "sub_agent_event",
        "run_completed",
        "context_compacted",
        "guardrail_triggered",
        "lockdown_engaged",
        "run_cancelled",
    }
)

# Same palette as ``share.py`` — warm orange on off-white, dark mode by query.
# Kept as its own sheet rather than imported because every rule here is
# prefixed, and the two surfaces have different layouts (a page vs. a card).
_STYLE = """
.sa-live {
  --sa-bg: #fff; --sa-line: #e8e6e3; --sa-text: #1c1b1a;
  --sa-muted: #6f6b66; --sa-faint: #9a958f;
  --sa-accent: #e8590c; --sa-accent-soft: #fdf0e8;
  --sa-danger: #c92a2a; --sa-ok: #2f9e44; --sa-chip: #f4f2f0;
  --sa-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sa-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--sa-bg); color: var(--sa-text);
  font: 14.5px/1.62 var(--sa-sans);
  border: 1px solid var(--sa-line); border-radius: 14px;
  max-width: 780px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.05);
}
@media (prefers-color-scheme: dark) {
  .sa-live {
    --sa-bg: #201e1d; --sa-line: #34312e; --sa-text: #eceae7;
    --sa-muted: #a9a39c; --sa-faint: #726c66;
    --sa-accent: #ff8040; --sa-accent-soft: #2e1f16;
    --sa-danger: #ff8787; --sa-ok: #69db7c; --sa-chip: #2a2725;
  }
}
.sa-live * { box-sizing: border-box; }
.sa-live .sa-head {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 18px; border-bottom: 1px solid var(--sa-line);
}
.sa-live .sa-title { font-weight: 600; font-size: 14px; letter-spacing: -.01em; }
.sa-live .sa-badge {
  font: 11px/1 var(--sa-mono); color: var(--sa-ok);
  background: var(--sa-chip); border-radius: 999px; padding: 5px 9px;
  display: inline-flex; align-items: center; gap: 6px;
}
.sa-live .sa-badge.done { color: var(--sa-muted); }
.sa-live .sa-dot {
  width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  animation: sa-pulse 1.4s ease-in-out infinite;
}
.sa-live .sa-badge.done .sa-dot { animation: none; }
@keyframes sa-pulse { 0%,100% { opacity: 1 } 50% { opacity: .25 } }
.sa-live .sa-body { padding: 18px 18px 6px; }
.sa-live .sa-ask {
  background: var(--sa-chip); border-radius: 14px;
  padding: 11px 15px; margin: 0 0 18px auto; max-width: 76%; width: fit-content;
}
.sa-live .sa-prose { margin: 14px 0; white-space: pre-wrap; }
.sa-live .sa-row {
  display: flex; gap: 11px; align-items: flex-start;
  margin: 12px 0; color: var(--sa-muted);
}
.sa-live .sa-glyph {
  font: 13px/1.5 var(--sa-mono); color: var(--sa-faint);
  width: 16px; flex: 0 0 16px; text-align: center; padding-top: 1px;
}
.sa-live .sa-label { flex: 1; min-width: 0; }
.sa-live .sa-label b { font-weight: 500; color: var(--sa-text); }
.sa-live .sa-targets {
  font: 12.5px/1.6 var(--sa-mono); color: var(--sa-faint);
  overflow-wrap: anywhere;
}
.sa-live .sa-run { color: var(--sa-accent); }
.sa-live .sa-err b { color: var(--sa-danger); }
.sa-live details.sa-call { margin: 6px 0 0; }
.sa-live details.sa-call > summary {
  cursor: pointer; list-style: none; font: 12px/1.6 var(--sa-mono);
  color: var(--sa-faint);
}
.sa-live details.sa-call > summary::-webkit-details-marker { display: none; }
.sa-live details.sa-call > summary:hover { color: var(--sa-accent); }
.sa-live pre.sa-out {
  font: 12px/1.55 var(--sa-mono); background: var(--sa-chip);
  border-radius: 8px; padding: 10px 12px; margin: 7px 0 0;
  max-height: 260px; overflow: auto; white-space: pre-wrap;
  overflow-wrap: anywhere; color: var(--sa-muted);
}
.sa-live .sa-approval {
  border: 1px solid var(--sa-line); border-radius: 12px;
  padding: 13px 15px; margin: 16px 0;
}
.sa-live .sa-approval .sa-bullet { color: var(--sa-accent); margin-right: 7px; }
.sa-live .sa-approval .sa-what { font-weight: 500; margin-bottom: 8px; }
.sa-live .sa-approval .sa-meta {
  font: 12px/1.6 var(--sa-mono); color: var(--sa-faint);
}
.sa-live .sa-choices {
  display: flex; gap: 16px; justify-content: flex-end;
  margin-top: 11px; font-size: 13px; color: var(--sa-muted);
}
.sa-live .sa-choices .sa-primary { color: var(--sa-text); font-weight: 600; }
.sa-live .sa-sub {
  border-left: 2px solid var(--sa-accent-soft);
  padding-left: 13px; margin: 14px 0;
}
.sa-live .sa-notice {
  font-size: 13px; color: var(--sa-muted);
  background: var(--sa-accent-soft); border-radius: 8px; padding: 9px 12px;
  margin: 14px 0;
}
.sa-live .sa-caret {
  display: inline-block; width: 7px; height: 1.05em; margin-left: 1px;
  background: var(--sa-accent); vertical-align: text-bottom;
  animation: sa-blink 1s steps(2) infinite;
}
@keyframes sa-blink { 50% { opacity: 0 } }
.sa-live pre.sa-tree {
  font: 12.5px/1.7 var(--sa-mono); margin: 4px 0 12px;
  white-space: pre; overflow-x: auto; color: var(--sa-text);
}
.sa-live .sa-foot {
  border-top: 1px solid var(--sa-line); padding: 11px 18px;
  font: 12px/1.5 var(--sa-mono); color: var(--sa-faint); text-align: right;
}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class LiveView:
    """A chat panel that redraws itself as events arrive.

    Feed it events and call :meth:`close`; in a notebook, prefer
    :func:`watch`, which does both around ``agent.stream()``.

    ``display=False`` makes it a pure renderer — :meth:`html` still returns
    the panel, and nothing touches IPython. That is how it is tested, and how
    you would embed it in a web app.
    """

    def __init__(
        self,
        *,
        prompt: str | None = None,
        title: str = "Agent run",
        model: str | None = None,
        cost_usd: float | None = None,
        display: bool = True,
        show_output: bool = True,
        output_limit: int = 4000,
        min_interval: float = 0.05,
        shape: str = "chat",
    ) -> None:
        if shape not in ("chat", "tree"):
            raise ValueError(f"Unknown shape {shape!r}. Valid shapes: chat, tree.")
        self.shape = shape
        self.prompt = prompt
        self.title = title
        self.model = model
        self.cost_usd = cost_usd
        self.show_output = show_output
        self.output_limit = output_limit
        self._min_interval = min_interval
        self._acc = WorkRunAccumulator()
        self._done = False
        self._last_draw = 0.0
        self._handle = self._open_display() if display else None

    # ── display plumbing ─────────────────────────────────────────────────

    def _open_display(self) -> Any:
        """A handle we can ``update()``, or ``None`` outside IPython.

        Import failure is not an error: the same object should work in a
        plain script, it just cannot animate there.
        """
        try:
            from IPython.display import HTML, display
        except ImportError:  # pragma: no cover - depends on the environment
            return None
        return display(HTML(self.html()), display_id=True)

    def _draw(self, *, force: bool) -> None:
        if self._handle is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_draw) < self._min_interval:
            return
        self._last_draw = now
        self._handle.update(self._payload())

    def _payload(self) -> Any:
        try:
            from IPython.display import HTML
        except ImportError:  # pragma: no cover - depends on the environment
            return self.html()
        return HTML(self.html())

    # ── ingest ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> None:
        self._acc.feed(event)
        if event.type == "run_completed":
            usage = dict(event.payload.get("usage") or {})
            if self.cost_usd is None and usage.get("cost_usd") is not None:
                self.cost_usd = float(usage["cost_usd"])
        if self.prompt is None and event.type == "run_started":
            self.prompt = str(event.payload.get("prompt") or "") or None
        self._draw(force=event.type in _STRUCTURAL)

    def close(self) -> None:
        self._acc.finish()
        self._done = True
        self._draw(force=True)

    # ── render ───────────────────────────────────────────────────────────

    def _repr_html_(self) -> str:
        return self.html()

    def html(self) -> str:
        body: list[str] = []
        if self.prompt:
            body.append(f'<div class="sa-ask">{_esc(self.prompt)}</div>')

        if self.shape == "tree":
            body.append(self._tree_html())
        else:
            rows = self._acc.rows if self._done else self._acc.live_rows()
            streaming_index = len(rows) - 1 if not self._done else -1
            for index, row in enumerate(rows):
                body.append(self._row_html(row, streaming=index == streaming_index))

        state = "done" if self._done else ""
        label = "Done" if self._done else "Live"
        return (
            f"<style>{_STYLE}</style>"
            f'<div class="sa-live">'
            f'<div class="sa-head">'
            f'<span class="sa-title">{_esc(self.title)}</span>'
            f'<span class="sa-badge {state}"><span class="sa-dot"></span>'
            f"{label}</span>"
            f"</div>"
            f'<div class="sa-body">{"".join(body)}</div>'
            f'<div class="sa-foot">{self._footer()}</div>'
            f"</div>"
        )

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

        if isinstance(row, WorkRow):
            return self._work_html(row.group.icon, row.group.label, row.group.calls)

        if isinstance(row, SubAgentRow):
            inner = self._work_html("↳", f"{row.agent} · {row.label}", row.calls)
            return f'<div class="sa-sub">{inner}</div>'

        if isinstance(row, ApprovalRow):
            return self._approval_html(row)

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
        return (
            f'<div class="{klass}">'
            f'<span class="sa-glyph">{_esc(icon)}</span>'
            f'<span class="sa-label"><b>{_esc(label)}</b>'
            f'{" ›" if not running else " …"}{detail}'
            f'{"".join(self._call_html(call) for call in calls)}'
            f"</span></div>"
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


def watch(
    agent: Any,
    prompt: str,
    *,
    title: str = "Agent run",
    show_output: bool = True,
    shape: str = "chat",
    **kwargs: Any,
) -> str:
    """Run *agent* with the live panel, and return the final answer.

    The notebook equivalent of :meth:`Agent.run_live`::

        answer = watch(agent, "Which accounts are at risk?")

    ``shape="tree"`` draws the compact tree instead of the chat rows — the
    same run, redrawn in place as it grows::

        Agent started
        │
        ├─ Understanding request
        │  Read the inbox, check the guest list, then save.
        │
        ├─ Tool group: Read 3 files
        │  └─ read_file                                completed  4ms
        │
        ├─ Decision
        │  Jordan is not on the list. Add the row.
        │
        └─ Final answer
           RSVP recorded.

    The panel keeps updating in the cell's output while the run proceeds; the
    call returns once the run is finished.
    """
    view = LiveView(
        prompt=prompt,
        title=title,
        model=getattr(getattr(agent, "llm", None), "model", None),
        show_output=show_output,
        shape=shape,
        **kwargs,
    )
    answer = ""
    try:
        for event in agent.stream(prompt):
            view.feed(event)
            if event.type == "run_completed":
                answer = str(event.payload.get("output", "") or "")
    finally:
        view.close()
    return answer


def watch_tree(agent: Any, prompt: str, **kwargs: Any) -> str:
    """:func:`watch` with the tree shape — structure instead of prose."""
    kwargs.setdefault("title", "Agent run")
    return watch(agent, prompt, shape="tree", **kwargs)


def render_chat_html(
    source: Iterable[AgentEvent] | Any,
    *,
    prompt: str | None = None,
    title: str = "Agent run",
    model: str | None = None,
    show_output: bool = True,
    shape: str = "chat",
) -> str:
    """A finished run as the same panel — no IPython, no live updates.

    Returns an HTML *fragment* (scoped styles included), so it can be dropped
    into a page, a report, or ``IPython.display.HTML``.
    """
    view = LiveView(
        prompt=prompt,
        title=title,
        model=model,
        display=False,
        show_output=show_output,
        shape=shape,
    )
    for event in getattr(source, "events", source):
        view.feed(event)
    view.close()
    return view.html()
