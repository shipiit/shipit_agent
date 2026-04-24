"""Live TUI renderer for ``Autopilot.stream()`` — Claude-Desktop-style.

Consumes the event stream from :meth:`Autopilot.stream` and prints a
continuously-updated summary to stdout. No heavy dependencies (no rich,
no textual) — just ANSI escapes, so it works anywhere a 2026 terminal
does.

Layout:

    ┌── Autopilot ── run-2026-04-21 ─────────────────
    │ Goal: Migrate every SQL query to parameterized form
    │ 3/5 criteria satisfied · 12 tools · 42s · 14k tokens
    │
    │ [tool] grep_search   (query='db.raw\\(')              ok
    │ [tool] read_file     (path='src/api/users.ts')        ok
    │ [tool] edit_file     (path='src/api/users.ts')        ok
    │ ...
    └────────────────────────────────────────────────

Also supports a plain JSON-lines mode for piping into jq / log sinks:
``--format jsonl``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable, TextIO

# ANSI helpers kept tiny — skip the chalk-ish libraries.
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"


def render_stream(
    events: Iterable[dict[str, Any]],
    *,
    out: TextIO | None = None,
    color: bool | None = None,
    fmt: str = "tui",
) -> dict[str, Any] | None:
    """Consume ``events`` and render them live. Returns the final
    ``autopilot.result`` payload, or ``None`` if the stream ended without one.

    ``fmt``:
      - ``"tui"``   — formatted terminal output (default).
      - ``"jsonl"`` — one JSON object per line; machine-readable.
      - ``"plain"`` — plain lines with no ANSI colour (CI logs).
    """
    out = out or sys.stdout
    use_color = _should_color(color, out) if fmt == "tui" else False
    result: dict[str, Any] | None = None

    renderer = {
        "jsonl": _render_jsonl,
        "plain": lambda ev, w: _render_tui(ev, w, use_color=False),
        "tui": lambda ev, w: _render_tui(ev, w, use_color=use_color),
    }.get(fmt, _render_jsonl)

    for ev in events:
        renderer(ev, out)
        if ev.get("kind") == "autopilot.result":
            result = ev
        try:
            out.flush()
        except Exception:  # noqa: BLE001
            pass

    return result


# ── renderers ────────────────────────────────────────────────────


def _render_jsonl(ev: dict[str, Any], out: TextIO) -> None:
    out.write(json.dumps(ev, default=_safe_default) + "\n")


def _render_tui(ev: dict[str, Any], out: TextIO, *, use_color: bool) -> None:
    kind = str(ev.get("kind", ""))
    c = _color(use_color)

    if kind == "autopilot.run_started":
        goal = ev.get("goal", {}) or {}
        obj = goal.get("objective", "(no objective)")
        resuming = " (resumed)" if ev.get("resuming") else ""
        out.write(c("cyan", f"\n┌── Autopilot ── {ev.get('run_id')}{resuming}\n"))
        out.write(c("cyan", "│ ") + c("bold", "Goal: ") + obj + "\n")
        criteria = goal.get("success_criteria") or []
        for i, crit in enumerate(criteria, 1):
            out.write(c("dim", f"│   {i}. {crit}\n"))
        out.write(c("cyan", "│\n"))
        return

    if kind == "autopilot.tool":
        msg = ev.get("message") or ev.get("kind")
        payload = ev.get("payload") or {}
        out.write(c("cyan", "│ ") + c("yellow", "[tool] ") + f"{msg}")
        if payload:
            preview = _short_payload(payload)
            if preview:
                out.write(c("dim", f"  {preview}"))
        out.write("\n")
        return

    if kind == "autopilot.iteration":
        met = ev.get("criteria_met") or []
        score = f"{sum(1 for c in met if c)}/{len(met)}"
        usage = ev.get("usage", {}) or {}
        out.write(
            c("cyan", "│ ")
            + c("green", "✓ iter ")
            + str(ev.get("iteration"))
            + c(
                "dim",
                f" — {score} criteria · {usage.get('tool_calls', 0)} tools · "
                f"{usage.get('seconds', 0):.0f}s · {usage.get('tokens', 0)} tok\n",
            )
        )
        summary = (ev.get("summary") or "").strip().split("\n", 1)[0]
        if summary:
            out.write(c("dim", "│   " + summary[:160] + "\n"))
        return

    if kind == "autopilot.heartbeat":
        usage = ev.get("usage", {}) or {}
        met = f"{ev.get('criteria_satisfied_count', 0)}/{ev.get('criteria_total', 0)}"
        out.write(
            c("cyan", "│ ")
            + c("magenta", "♥ heartbeat")
            + c(
                "dim",
                f" iter={ev.get('iteration')} criteria={met} "
                f"t={usage.get('seconds', 0):.0f}s\n",
            )
        )
        return

    if kind == "autopilot.budget_exceeded":
        out.write(
            c("cyan", "│ ") + c("red", "⛔ budget: ") + str(ev.get("reason", "")) + "\n"
        )
        return

    if kind == "autopilot.criteria_satisfied":
        out.write(c("cyan", "│ ") + c("green", "🎯 all criteria satisfied\n"))
        return

    if kind == "autopilot.stream_fallback":
        out.write(
            c("cyan", "│ ")
            + c("yellow", "↪ stream fallback: ")
            + str(ev.get("error", ""))
            + "\n"
        )
        return

    if kind == "autopilot.result":
        status = str(ev.get("status", "unknown"))
        color_name = {
            "completed": "green",
            "partial": "yellow",
            "halted": "yellow",
            "failed": "red",
        }.get(status, "dim")
        usage = ev.get("usage", {}) or {}
        out.write(
            c("cyan", "└── result: ")
            + c(color_name, status.upper())
            + c(
                "dim",
                f" · {ev.get('iterations')} iters · "
                f"{usage.get('tool_calls', 0)} tools · "
                f"{usage.get('seconds', 0):.0f}s · "
                f"{usage.get('tokens', 0)} tok\n",
            )
        )
        reason = ev.get("halt_reason")
        if reason:
            out.write(c("dim", f"   halt: {reason}\n"))
        out.write("\n")
        return

    # Fallback for unknown event kinds — keep the stream honest.
    out.write(c("dim", f"│ {kind}\n"))


# ── helpers ──────────────────────────────────────────────────────


def _should_color(override: bool | None, out: TextIO) -> bool:
    if override is not None:
        return override
    if not hasattr(out, "isatty") or not out.isatty():
        return False
    return not _env_says_no_color()


def _env_says_no_color() -> bool:
    import os

    return "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb"


def _color(enabled: bool):
    palette = {
        "bold": BOLD,
        "dim": DIM,
        "cyan": CYAN,
        "green": GREEN,
        "yellow": YELLOW,
        "red": RED,
        "magenta": MAGENTA,
    }
    if not enabled:
        return lambda _name, text: text
    return lambda name, text: f"{palette.get(name, '')}{text}{RESET}"


def _short_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for k, v in payload.items():
        if k in ("text", "content", "body"):
            preview = str(v).replace("\n", " ")[:40]
            parts.append(f"{k}={preview!r}")
        elif isinstance(v, (str, int, float, bool)):
            parts.append(f"{k}={str(v)[:40]}")
        if len(parts) >= 3:
            break
    return "(" + ", ".join(parts) + ")" if parts else ""


def _safe_default(v: Any) -> Any:
    try:
        return str(v)
    except Exception:  # noqa: BLE001
        return "<unserializable>"
