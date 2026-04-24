"""Fan-out — dispatch N child Autopilots in parallel, aggregate the results.

The single biggest workload-unlock for long-running agents: "audit every
PR merged today" / "research every top-50 account" / "migrate every SQL
call in src/". Sequential iteration burns wall-clock; parallel dispatch
turns an overnight job into minutes.

Contract::

    autopilot = Autopilot(llm=llm, goal=Goal("..."), budget=BudgetPolicy())
    result = autopilot.fanout(
        items=["PR-1", "PR-2", "PR-3", ...],
        objective_template="Security-review {item}",
        criteria_template=["No high-severity finding", "Has regression test"],
        max_parallel=5,
        child_budget_frac=0.2,
    )

    for child in result.children:
        print(child.run_id, child.status, child.iterations)

Budget safety: each child receives ``child_budget_frac * parent.budget``
— by default 20%. That way a 10-item fan-out with the parent cap at
30 min doesn't individually burn 5 hours in aggregate; each child is
capped at 6 min, the whole batch at ~30 min wall-clock.

No process-level concurrency — we use a ThreadPoolExecutor since the
hot path is I/O-bound (LLM + tool calls). If you're CPU-bound, drive
parallelism outside the agent layer.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field  # asdict used for event payloads
from threading import Lock
from typing import Any, Callable, Iterator

from shipit_agent.deep.goal_agent import Goal

from .budget import BudgetPolicy
from .core import Autopilot
from .result import AutopilotResult


# ─────────────────────── result envelope ───────────────────────


@dataclass(slots=True)
class FanoutResult:
    """Aggregate envelope returned by :meth:`Autopilot.fanout`.

    ``status`` rollup:
      - ``completed`` — every child finished ``completed``.
      - ``partial``    — some children completed; others partial/halted.
      - ``failed``     — every child failed.
    """

    parent_run_id: str
    objective_template: str
    status: str = "unknown"
    children: list[dict[str, Any]] = field(default_factory=list)
    aggregated_output: str = ""
    wall_seconds: float = 0.0
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────── fan-out driver ───────────────────────


def autopilot_fanout(
    self: Autopilot,
    items: list[Any],
    *,
    objective_template: str,
    criteria_template: list[str] | None = None,
    max_parallel: int = 5,
    child_budget_frac: float = 0.2,
    aggregator: Callable[[list[AutopilotResult]], str] | None = None,
    parent_run_id: str | None = None,
) -> FanoutResult:
    """Run a parallel batch of Autopilots, one per item.

    Each child is a fresh Autopilot with:
      - ``goal``: `Goal(objective=template.format(item=item), success_criteria=criteria_template or [])`
      - ``budget``: the parent budget scaled by ``child_budget_frac``.
      - ``run_id``: ``f"{parent_run_id}.{slugged-item}"``.

    Children run concurrently up to ``max_parallel``. Returns a
    :class:`FanoutResult` with each child's ``AutopilotResult``.
    """
    if not items:
        return FanoutResult(
            parent_run_id=parent_run_id or "fanout-empty",
            objective_template=objective_template,
            status="completed",
            aggregated_output="(no items)",
        )

    prid = parent_run_id or f"fanout-{int(time.time())}"
    child_budget = _scale_budget(self.budget, child_budget_frac)
    max_workers = max(1, min(max_parallel, len(items)))

    started = time.monotonic()
    children_out: list[AutopilotResult] = []
    failed_ids: list[str] = []
    lock = Lock()

    def _child_run(idx: int, item: Any) -> AutopilotResult:
        run_id = f"{prid}.{_slug(item)}-{idx}"
        # Never mutate the parent Autopilot — build a fresh one per child.
        child = Autopilot(
            llm=self.llm,
            goal=Goal(
                objective=objective_template.format(item=item),
                success_criteria=list(criteria_template or []),
            ),
            tools=list(self.tools),
            mcps=list(self.mcps),
            budget=child_budget,
            checkpoint_dir=self.checkpoints.directory,
            heartbeat_every_seconds=self.heartbeat_every_seconds,
            on_heartbeat=self.on_heartbeat,
            use_builtins=self.use_builtins,
            agent_factory=self.agent_factory,
            **self.agent_kwargs,
        )
        try:
            return child.run(run_id=run_id)
        except Exception as err:  # noqa: BLE001
            with lock:
                failed_ids.append(run_id)
            return AutopilotResult(
                run_id=run_id,
                status="failed",
                halt_reason=f"child exception: {type(err).__name__}: {err}",
            )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_child_run, i, item) for i, item in enumerate(items)]
        for f in as_completed(futures):
            children_out.append(f.result())

    # Preserve item order in the output — as_completed returns out-of-order.
    children_out.sort(key=lambda r: r.run_id)

    # The `failed` list should include every child that didn't complete
    # successfully — whether that was an exception escape OR an inner
    # agent that returned status=failed without raising.
    for r in children_out:
        if r.status == "failed" and r.run_id not in failed_ids:
            failed_ids.append(r.run_id)

    aggregated = (aggregator or _default_aggregator)(children_out)
    status = _rollup_status([r.status for r in children_out])

    return FanoutResult(
        parent_run_id=prid,
        objective_template=objective_template,
        status=status,
        children=[r.to_dict() for r in children_out],
        aggregated_output=aggregated,
        wall_seconds=time.monotonic() - started,
        failed=failed_ids,
    )


def autopilot_fanout_stream(
    self: Autopilot,
    items: list[Any],
    *,
    objective_template: str,
    criteria_template: list[str] | None = None,
    max_parallel: int = 5,
    child_budget_frac: float = 0.2,
    aggregator: Callable[[list[AutopilotResult]], str] | None = None,
    parent_run_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Streaming variant — yields an event per child as it completes.

    Event kinds:
      - ``autopilot.fanout_started``   {"parent_run_id", "items", "child_budget"}
      - ``autopilot.fanout_child``     {"run_id", "status", "iterations", "item_index"}
      - ``autopilot.fanout_result``    the final :class:`FanoutResult` dict
    """
    prid = parent_run_id or f"fanout-{int(time.time())}"
    child_budget = _scale_budget(self.budget, child_budget_frac)
    started = time.monotonic()
    yield {
        "kind": "autopilot.fanout_started",
        "parent_run_id": prid,
        "items": [str(i) for i in items][:50],  # cap to keep event size sane
        "total": len(items),
        # `asdict` works with slots=True; accessing __dict__ does not.
        "child_budget": asdict(child_budget),
        "max_parallel": max_parallel,
    }

    if not items:
        result = FanoutResult(
            parent_run_id=prid,
            objective_template=objective_template,
            status="completed",
            aggregated_output="(no items)",
            wall_seconds=0.0,
        )
        yield {"kind": "autopilot.fanout_result", **result.to_dict()}
        return

    max_workers = max(1, min(max_parallel, len(items)))
    children_out: list[AutopilotResult] = []
    failed: list[str] = []

    def _child_run(idx: int, item: Any) -> tuple[int, AutopilotResult]:
        run_id = f"{prid}.{_slug(item)}-{idx}"
        child = Autopilot(
            llm=self.llm,
            goal=Goal(
                objective=objective_template.format(item=item),
                success_criteria=list(criteria_template or []),
            ),
            tools=list(self.tools),
            mcps=list(self.mcps),
            budget=child_budget,
            checkpoint_dir=self.checkpoints.directory,
            heartbeat_every_seconds=self.heartbeat_every_seconds,
            on_heartbeat=self.on_heartbeat,
            use_builtins=self.use_builtins,
            agent_factory=self.agent_factory,
            **self.agent_kwargs,
        )
        try:
            return idx, child.run(run_id=run_id)
        except Exception as err:  # noqa: BLE001
            failed.append(run_id)
            return idx, AutopilotResult(
                run_id=run_id,
                status="failed",
                halt_reason=f"child exception: {type(err).__name__}: {err}",
            )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_child_run, i, item) for i, item in enumerate(items)]
        for f in as_completed(futures):
            idx, res = f.result()
            children_out.append(res)
            yield {
                "kind": "autopilot.fanout_child",
                "item_index": idx,
                "run_id": res.run_id,
                "status": res.status,
                "iterations": res.iterations,
                "halt_reason": res.halt_reason,
            }

    children_out.sort(key=lambda r: r.run_id)
    aggregated = (aggregator or _default_aggregator)(children_out)
    status = _rollup_status([r.status for r in children_out])

    yield {
        "kind": "autopilot.fanout_result",
        **FanoutResult(
            parent_run_id=prid,
            objective_template=objective_template,
            status=status,
            children=[r.to_dict() for r in children_out],
            aggregated_output=aggregated,
            wall_seconds=time.monotonic() - started,
            failed=list(failed),
        ).to_dict(),
    }


# ─────────────────────── helpers ───────────────────────


def _scale_budget(parent: BudgetPolicy, frac: float) -> BudgetPolicy:
    """Return a new BudgetPolicy whose caps are the parent's * frac."""
    frac = max(0.05, min(1.0, frac))

    def _scale(v: int | float | None) -> int | float | None:
        if v in (None, 0):
            return v
        if isinstance(v, int):
            return max(1, int(v * frac))
        return max(1.0, v * frac)

    return BudgetPolicy(
        max_seconds=_scale(parent.max_seconds),
        max_tool_calls=_scale(parent.max_tool_calls),
        max_tokens=_scale(parent.max_tokens),
        max_dollars=_scale(parent.max_dollars),
        max_iterations=_scale(parent.max_iterations),
    )


def _default_aggregator(children: list[AutopilotResult]) -> str:
    """Stitch child outputs into a single markdown digest."""
    if not children:
        return "(no children)"
    lines: list[str] = [f"# Fan-out digest — {len(children)} children\n"]
    for c in children:
        header = f"## {c.run_id} · {c.status.upper()} · {c.iterations} iters"
        body = (c.output or "").strip()
        if len(body) > 1500:
            body = body[:1500] + "\n…(truncated)"
        lines.append(f"{header}\n\n{body}\n")
    return "\n".join(lines)


def _rollup_status(statuses: list[str]) -> str:
    if not statuses:
        return "completed"
    if all(s == "completed" for s in statuses):
        return "completed"
    if all(s == "failed" for s in statuses):
        return "failed"
    return "partial"


def _slug(item: Any) -> str:
    """Make a filesystem-safe id fragment out of whatever the user passed.

    Strip any leading/trailing dots OR dashes so paths like "../etc/passwd"
    don't round-trip as "..-etc-passwd" (which still looks like a path
    traversal and breaks the expected "etc-passwd" slug).
    """
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item).strip().lower())
    return s.strip(".-")[:48] or "item"


# Attach the methods onto Autopilot so callers can do `autopilot.fanout(...)`.
Autopilot.fanout = autopilot_fanout  # type: ignore[attr-defined]
Autopilot.fanout_stream = autopilot_fanout_stream  # type: ignore[attr-defined]
