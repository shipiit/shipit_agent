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

import time
from typing import Any, Iterable

from shipit_agent.core.models import AgentEvent

from .grouping import (
    WorkRunAccumulator,
)
from .live_ui_html import LiveViewHtmlMixin, _esc
from .live_ui_style import _STYLE

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

class LiveView(LiveViewHtmlMixin):
    """A chat panel that redraws itself as events arrive.

    Feed it events and call :meth:`close`; in a notebook, prefer
    :func:`watch`, which does both around ``agent.stream()``.

    ``output_limit=None`` shows every byte a tool returned rather than the
    first few thousand; each output scrolls in its own box, so nothing is
    hidden and the page does not grow without bound.

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
        output_limit: int | None = 4000,
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


def watch(
    agent: Any,
    prompt: str,
    *,
    title: str = "Agent run",
    show_output: bool = True,
    shape: str = "chat",
    output_limit: int | None = 4000,
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
        output_limit=output_limit,
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
    output_limit: int | None = 4000,
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
        output_limit=output_limit,
    )
    for event in getattr(source, "events", source):
        view.feed(event)
    view.close()
    return view.html()
