"""Autopilot — the long-running "keep working until goal is met" runner.

Composes the inner ``GoalAgent`` with budget gates, persistent checkpoints,
and heartbeat telemetry. See :mod:`shipit_agent.autopilot` for the package
overview and ``streaming.py`` for the :meth:`Autopilot.stream` generator.

24-hour-run hardening notes:

* ``run()``/``stream()`` both resume *cumulatively* — wall-clock seconds,
  tokens, dollars, and tool-call totals reload from the checkpoint, so a
  run that crashes at hour 12 and resumes for another 12 hours trips a
  24-hour cap exactly at hour 24 (not hour 36).
* ``SIGTERM`` is caught alongside ``SIGINT`` (systemd/launchd send
  SIGTERM on stop) and triggers a clean halt with one final checkpoint.
* Dollar tracking uses the pricing table in :mod:`shipit_agent.costs`;
  callers can turn it off with ``track_dollars=False`` or override
  pricing by passing a :class:`~shipit_agent.costs.tracker.CostTracker`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from shipit_agent.deep.goal_agent import Goal
from shipit_agent.safety.askuser_channel import pending_questions

from .accounting import _AutopilotAccounting
from .artifacts import ArtifactCollector
from .budget import BudgetPolicy
from .checkpoint import CheckpointStore
from .critic import Critic
from .iteration import _AutopilotIteration
from .pricing import (
    _lookup_dollars as _lookup_dollars,
)
from .pricing import (
    _resolve_pricing as _resolve_pricing,
)
from .reporting import _AutopilotReporting
from .result import AutopilotResult
from .signals import _SignalGuard

HeartbeatCallback = Callable[[dict[str, Any]], None]


class Autopilot(_AutopilotIteration, _AutopilotAccounting, _AutopilotReporting):
    """Drive an agent to goal completion under a budget.

    The inner agent is :class:`GoalAgent` by default; pass
    ``agent_factory`` for anything custom. The only contract is that the
    factory builds an object with a ``run()`` method returning something
    duck-compatible with :class:`GoalResult`.
    """

    def __init__(
        self,
        *,
        llm: Any,
        goal: Goal,
        tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        budget: BudgetPolicy | None = None,
        checkpoint_dir: str | Path | None = None,
        heartbeat_every_seconds: float = 60.0,
        on_heartbeat: HeartbeatCallback | None = None,
        use_builtins: bool = False,
        agent_factory: Callable[..., Any] | None = None,
        # New: reflection + deliverables hooks.
        critic: Critic | bool | None = None,
        artifacts: ArtifactCollector | bool | None = None,
        # New: cost tracking + signal handling.
        track_dollars: bool = True,
        cost_tracker: Any | None = None,
        install_signal_handlers: bool = True,
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.goal = goal
        self.tools = tools or []
        self.mcps = mcps or []
        self.budget = budget or BudgetPolicy()
        self.checkpoints = CheckpointStore(
            checkpoint_dir or (Path.home() / ".shipit_agent" / "checkpoints")
        )
        self.heartbeat_every_seconds = max(1.0, heartbeat_every_seconds)
        self.on_heartbeat = on_heartbeat
        self.use_builtins = use_builtins
        self.agent_factory = agent_factory
        self.agent_kwargs = agent_kwargs
        self.track_dollars = track_dollars
        self.cost_tracker = cost_tracker
        self.install_signal_handlers = install_signal_handlers

        # Critic: `True` → build a default critic that shares our LLM.
        # Instance → use directly. `None`/`False` → no critic loop.
        if critic is True:
            self.critic: Critic | None = Critic()
        elif isinstance(critic, Critic):
            self.critic = critic
        else:
            self.critic = None

        # Artifact collector: `True` → build a default in-memory collector.
        if artifacts is True:
            self.artifacts: ArtifactCollector | None = ArtifactCollector()
        elif isinstance(artifacts, ArtifactCollector):
            self.artifacts = artifacts
        else:
            self.artifacts = None

        # Set by signal handler; the loop checks it between iterations.
        self._stop_requested: str = ""

    # ── public API ───────────────────────────────────────────────

    def run(
        self, run_id: str | None = None, *, resume: bool = False
    ) -> AutopilotResult:
        """Execute the goal loop synchronously; returns an AutopilotResult.

        Pass ``resume=True`` to pick up from an existing checkpoint. Without
        that flag, an existing checkpoint with the same ``run_id`` raises
        ``FileExistsError`` to protect against accidental re-runs.
        """
        rid = run_id or f"run-{int(time.time())}"
        if self.checkpoints.exists(rid) and not resume:
            raise FileExistsError(
                f"Checkpoint exists for run_id={rid!r}. "
                "Pass resume=True to continue or delete the file."
            )
        prior = self.checkpoints.load(rid) if resume else {}

        # Restore the FULL usage from the prior checkpoint (not just
        # iterations). Without this a 12h-crash + 12h-resume would reset
        # seconds/tokens/dollars and blow through any 24h cap.
        usage = CheckpointStore.usage_from_payload(prior)
        prior_seconds = usage.seconds
        step_outputs: list[dict[str, Any]] = list(prior.get("step_outputs", []))
        # Anchor `started` so `usage.seconds` is *cumulative* across resume.
        started = time.monotonic() - prior_seconds
        last_hb = time.monotonic()
        final_output = str(prior.get("output", ""))
        criteria_met = [False] * len(self.goal.success_criteria)
        halt_reason = ""

        # If we're resuming AND there's still an unanswered question on
        # the ask_user channel, stop immediately — don't spend an
        # iteration re-asking. The user hasn't answered yet.
        if resume and pending_questions(rid):
            halt_reason = "awaiting user answer (ask_user_async)"
            return self._make_awaiting_result(
                rid,
                usage,
                criteria_met,
                final_output,
                halt_reason,
                step_outputs,
            )

        with self._signal_guard():
            try:
                while True:
                    usage.seconds = time.monotonic() - started
                    usage.iterations += 1

                    exceeded, reason = self.budget.exceeded(usage)
                    if exceeded:
                        halt_reason = reason
                        break

                    if self._stop_requested:
                        halt_reason = self._stop_requested
                        break

                    result = self._build_inner_agent().run()
                    final_output = (
                        getattr(result, "output", final_output) or final_output
                    )
                    criteria_met = list(getattr(result, "criteria_met", criteria_met))
                    usage.tool_calls += self._count_tool_calls(result)
                    iteration_tokens = self._count_tokens(result)
                    usage.tokens += iteration_tokens
                    usage.dollars += self._count_dollars(result, iteration_tokens)

                    # Artifact extraction — best-effort, never fail the run on it.
                    if self.artifacts is not None:
                        try:
                            self.artifacts.extract_from_output(
                                final_output, iteration=usage.iterations
                            )
                        except Exception:  # noqa: BLE001
                            pass

                    # Critic loop — if the verdict says all criteria met with
                    # high confidence, we honor it (overriding the inner agent).
                    # If it disagrees, we feed suggestions via `agent_kwargs`
                    # into the next iteration's prompt.
                    latest_verdict, criteria_met = self._apply_critic(
                        final_output, criteria_met
                    )

                    step_outputs.append(
                        {
                            "iteration": usage.iterations,
                            "status": getattr(result, "goal_status", "unknown"),
                            "criteria_met": criteria_met,
                            "summary": final_output[:500],
                        }
                    )

                    now = time.monotonic()
                    # Emit a heartbeat on iteration 1 OR after the interval
                    # elapses — without the iter-1 path, a long first step
                    # looks indistinguishable from a hang.
                    if self.on_heartbeat and (
                        usage.iterations == 1
                        or (now - last_hb) >= self.heartbeat_every_seconds
                    ):
                        self._emit_heartbeat(
                            usage, criteria_met, step_outputs[-1]["summary"]
                        )
                        last_hb = now

                    if criteria_met and all(criteria_met):
                        halt_reason = "all criteria satisfied"
                        break
                    if self.critic is not None and self.critic.should_terminate(
                        latest_verdict
                    ):
                        halt_reason = "critic confirmed satisfaction"
                        break
                    if getattr(result, "goal_status", None) == "completed":
                        halt_reason = "inner agent reported completion"
                        break
                    if pending_questions(rid):
                        # An `ask_user_async` tool call put a question on the
                        # channel. Halt cleanly so the scheduler can park the run.
                        halt_reason = "awaiting user answer (ask_user_async)"
                        self._checkpoint(rid, usage, step_outputs, final_output)
                        return self._make_awaiting_result(
                            rid,
                            usage,
                            criteria_met,
                            final_output,
                            halt_reason,
                            step_outputs,
                        )

                    self._checkpoint(rid, usage, step_outputs, final_output)
            except KeyboardInterrupt:
                halt_reason = "interrupted by user (SIGINT)"
            except Exception as err:  # noqa: BLE001
                halt_reason = f"exception: {type(err).__name__}: {err}"
                self._checkpoint(rid, usage, step_outputs, final_output)
                return self._make_result(
                    rid,
                    "failed",
                    criteria_met,
                    usage,
                    final_output,
                    halt_reason,
                    step_outputs,
                )

        self._checkpoint(rid, usage, step_outputs, final_output)
        status = self._classify_status(criteria_met)
        return self._make_result(
            rid, status, criteria_met, usage, final_output, halt_reason, step_outputs
        )

    def resume(self, run_id: str) -> AutopilotResult:
        """Continue a previously checkpointed run."""
        return self.run(run_id=run_id, resume=True)

    # ── helpers shared with the streaming variant ────────────────

    # ── signal handling ──────────────────────────────────────────

    _SignalGuard = _SignalGuard

    def _signal_guard(self) -> "Autopilot._SignalGuard":
        return Autopilot._SignalGuard(self)


# ── pricing lookup helpers ───────────────────────────────────
