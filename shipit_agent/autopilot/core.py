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

import signal
import time
from pathlib import Path
from typing import Any, Callable

from shipit_agent.askuser_channel import pending_questions
from shipit_agent.deep.goal_agent import Goal, GoalAgent

from .artifacts import ArtifactCollector
from .budget import BudgetPolicy, BudgetUsage
from .checkpoint import CheckpointStore
from .critic import Critic, CriticVerdict
from .events import looks_like_tool_event
from .result import AutopilotResult


HeartbeatCallback = Callable[[dict[str, Any]], None]


class Autopilot:
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

    def run(self, run_id: str | None = None, *, resume: bool = False) -> AutopilotResult:
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
                rid, usage, criteria_met, final_output, halt_reason, step_outputs,
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
                    final_output = getattr(result, "output", final_output) or final_output
                    criteria_met = list(getattr(result, "criteria_met", criteria_met))
                    usage.tool_calls += self._count_tool_calls(result)
                    iteration_tokens = self._count_tokens(result)
                    usage.tokens += iteration_tokens
                    usage.dollars += self._count_dollars(result, iteration_tokens)

                    # Artifact extraction — best-effort, never fail the run on it.
                    if self.artifacts is not None:
                        try:
                            self.artifacts.extract_from_output(final_output, iteration=usage.iterations)
                        except Exception:   # noqa: BLE001
                            pass

                    # Critic loop — if the verdict says all criteria met with
                    # high confidence, we honor it (overriding the inner agent).
                    # If it disagrees, we feed suggestions via `agent_kwargs`
                    # into the next iteration's prompt.
                    if self.critic is not None:
                        latest_verdict = self.critic.review(
                            objective=self.goal.objective,
                            criteria=self.goal.success_criteria,
                            output=final_output,
                            fallback_llm=self.llm,
                        )
                        # Only trust the critic's flag-flips when its stated
                        # confidence meets the gate. A low-confidence "yes" is
                        # still useful as feedback (suggestions) but shouldn't
                        # short-circuit the loop.
                        if (
                            any(latest_verdict.criteria_met)
                            and latest_verdict.confidence >= self.critic.confidence_threshold
                        ):
                            criteria_met = list(latest_verdict.criteria_met)
                        self._stash_critic_suggestions(latest_verdict)
                    else:
                        latest_verdict = CriticVerdict()

                    step_outputs.append({
                        "iteration": usage.iterations,
                        "status": getattr(result, "goal_status", "unknown"),
                        "criteria_met": criteria_met,
                        "summary": final_output[:500],
                    })

                    now = time.monotonic()
                    # Emit a heartbeat on iteration 1 OR after the interval
                    # elapses — without the iter-1 path, a long first step
                    # looks indistinguishable from a hang.
                    if self.on_heartbeat and (
                        usage.iterations == 1 or (now - last_hb) >= self.heartbeat_every_seconds
                    ):
                        self._emit_heartbeat(usage, criteria_met, step_outputs[-1]["summary"])
                        last_hb = now

                    if criteria_met and all(criteria_met):
                        halt_reason = "all criteria satisfied"
                        break
                    if self.critic is not None and self.critic.should_terminate(latest_verdict):
                        halt_reason = "critic confirmed satisfaction"
                        break
                    if getattr(result, "goal_status", None) == "completed":
                        halt_reason = "inner agent reported completion"
                        break
                    if pending_questions(rid):
                        # An `ask_user_async` tool call put a question on the
                        # channel. Halt cleanly so the scheduler can park the run.
                        halt_reason = "awaiting user answer (ask_user_async)"
                        self.checkpoints.save(
                            rid, goal=self.goal_dict(), usage=usage,
                            step_outputs=step_outputs, output=final_output,
                        )
                        return self._make_awaiting_result(
                            rid, usage, criteria_met, final_output, halt_reason, step_outputs,
                        )

                    self.checkpoints.save(
                        rid, goal=self.goal_dict(), usage=usage,
                        step_outputs=step_outputs, output=final_output,
                    )
            except KeyboardInterrupt:
                halt_reason = "interrupted by user (SIGINT)"
            except Exception as err:  # noqa: BLE001
                halt_reason = f"exception: {type(err).__name__}: {err}"
                self.checkpoints.save(
                    rid, goal=self.goal_dict(), usage=usage,
                    step_outputs=step_outputs, output=final_output,
                )
                return self._make_result(
                    rid, "failed", criteria_met, usage, final_output, halt_reason, step_outputs
                )

        self.checkpoints.save(
            rid, goal=self.goal_dict(), usage=usage,
            step_outputs=step_outputs, output=final_output,
        )
        status = self._classify_status(criteria_met)
        return self._make_result(
            rid, status, criteria_met, usage, final_output, halt_reason, step_outputs
        )

    def resume(self, run_id: str) -> AutopilotResult:
        """Continue a previously checkpointed run."""
        return self.run(run_id=run_id, resume=True)

    # ── helpers shared with the streaming variant ────────────────

    def goal_dict(self) -> dict[str, Any]:
        return {
            "objective": self.goal.objective,
            "success_criteria": list(self.goal.success_criteria),
            "max_steps": self.goal.max_steps,
        }

    def _build_inner_agent(self) -> Any:
        if self.agent_factory is not None:
            return self.agent_factory(
                llm=self.llm, goal=self.goal,
                tools=self.tools, mcps=self.mcps, **self.agent_kwargs,
            )
        return GoalAgent(
            llm=self.llm, tools=list(self.tools),
            mcps=list(self.mcps), goal=self.goal,
            use_builtins=self.use_builtins, **self.agent_kwargs,
        )

    @staticmethod
    def _count_tool_calls(result: Any) -> int:
        for attr in ("step_outputs", "steps", "events"):
            items = getattr(result, attr, None)
            if items is not None:
                try:
                    return sum(1 for i in items if looks_like_tool_event(i))
                except Exception:
                    continue
        return 0

    @staticmethod
    def _count_tokens(result: Any) -> int:
        meta = getattr(result, "metadata", None)
        if isinstance(meta, dict):
            usage = meta.get("usage")
            if isinstance(usage, dict):
                total = usage.get("total_tokens")
                if isinstance(total, int):
                    return total
                return int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
        return 0

    def _count_dollars(self, result: Any, iteration_tokens: int) -> float:
        """Best-effort dollar attribution for one iteration.

        Order of preference:
          1. An explicit :class:`CostTracker` was passed — delegate to it.
          2. Result carries ``metadata.cost_usd`` — trust the provider.
          3. Result has a model name + token counts — look up pricing.
          4. Fall back to a coarse $/1k estimate from token counts.
        """
        if not self.track_dollars:
            return 0.0

        meta = getattr(result, "metadata", None) or {}
        if isinstance(meta, dict):
            explicit = meta.get("cost_usd")
            if isinstance(explicit, (int, float)):
                return float(explicit)

        # Attempt pricing-table lookup for known models.
        model = None
        if isinstance(meta, dict):
            model = meta.get("model") or meta.get("model_name")
        usage = meta.get("usage") if isinstance(meta, dict) else None
        input_tok = 0
        output_tok = 0
        if isinstance(usage, dict):
            input_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            output_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

        if model and (input_tok or output_tok):
            dollars = _lookup_dollars(model, input_tok, output_tok)
            if dollars > 0:
                return dollars

        # Fallback: a very rough blended $0.002 / 1k tokens estimate. Good
        # enough to keep the dollar counter non-zero for providers we don't
        # have pricing for — better than silently reporting $0 forever.
        if iteration_tokens and model:
            return iteration_tokens * 0.002 / 1000.0
        return 0.0

    @staticmethod
    def _classify_status(criteria_met: list[bool]) -> str:
        if criteria_met and all(criteria_met):
            return "completed"
        if criteria_met and any(criteria_met):
            return "partial"
        return "halted"

    def _emit_heartbeat(
        self, usage: BudgetUsage, criteria_met: list[bool], last_summary: str
    ) -> None:
        if not self.on_heartbeat:
            return
        payload = {
            "iteration": usage.iterations,
            "usage": usage.to_dict(),
            "remaining": self.budget.remaining(usage),
            "criteria_met": criteria_met,
            "criteria_satisfied_count": sum(1 for c in criteria_met if c),
            "criteria_total": len(criteria_met),
            "last_summary": last_summary,
        }
        try:
            self.on_heartbeat(payload)
        except Exception:   # noqa: BLE001
            pass

    def _stash_critic_suggestions(self, verdict: CriticVerdict) -> None:
        """Snapshot the latest verdict AND (when useful) feed its suggestions
        into the next inner-agent invocation's prompt.

        GoalAgent accepts a ``prompt`` kwarg — we mutate it in-place so the
        next iteration sees the feedback. Restored each iteration so stale
        suggestions don't accumulate across runs.
        """
        # Always snapshot the verdict — the final AutopilotResult surfaces
        # it regardless of whether the critic produced suggestions.
        self._last_verdict = verdict

        if not verdict.suggestions:
            self.agent_kwargs.pop("_critic_injected_prompt", None)
            return
        from .critic import inject_suggestions_into_prompt
        base = self.agent_kwargs.get("prompt") or "You are a helpful assistant. Complete the task thoroughly."
        self.agent_kwargs["prompt"] = inject_suggestions_into_prompt(base, verdict)
        self.agent_kwargs["_critic_injected_prompt"] = True

    def _make_awaiting_result(
        self,
        run_id: str, usage: BudgetUsage, criteria_met: list[bool],
        output: str, halt_reason: str, step_outputs: list[dict[str, Any]],
    ) -> AutopilotResult:
        """Short-circuit factory for the `awaiting_user` halt status."""
        return AutopilotResult(
            run_id=run_id, status="awaiting_user",
            goal=self.goal_dict(),
            criteria_met=criteria_met,
            iterations=usage.iterations,
            usage=usage.to_dict(),
            output=output, halt_reason=halt_reason,
            step_outputs=step_outputs,
            artifacts=[a.to_dict() for a in self.artifacts.all()] if self.artifacts else [],
        )

    def _make_result(
        self,
        run_id: str, status: str, criteria_met: list[bool],
        usage: BudgetUsage, output: str, halt_reason: str,
        step_outputs: list[dict[str, Any]],
    ) -> AutopilotResult:
        verdict = getattr(self, "_last_verdict", None)
        return AutopilotResult(
            run_id=run_id, status=status,
            criteria_met=criteria_met,
            iterations=usage.iterations,
            usage=usage.to_dict(),
            output=output, halt_reason=halt_reason,
            step_outputs=step_outputs,
            artifacts=[a.to_dict() for a in self.artifacts.all()] if self.artifacts else [],
            critic_verdict=verdict.to_dict() if verdict else {},
        )

    # ── signal handling ──────────────────────────────────────────

    def request_stop(self, reason: str = "stop requested") -> None:
        """Ask the loop to halt cleanly at the next iteration boundary.

        Safe to call from any thread or a signal handler. The loop
        finishes the current iteration's save, then exits normally with
        ``halt_reason`` set to ``reason``.
        """
        self._stop_requested = reason

    class _SignalGuard:
        """Install SIGTERM/SIGHUP handlers on entry, restore on exit.

        SIGINT already maps to KeyboardInterrupt by default, so we don't
        need to swap its handler — the try/except in the main loop
        catches the interrupt and drains a final checkpoint.
        """

        def __init__(self, autopilot: "Autopilot") -> None:
            self.autopilot = autopilot
            self._old: dict[int, Any] = {}

        def __enter__(self) -> None:
            if not self.autopilot.install_signal_handlers:
                return
            # Only attempt signal install on the main thread — signals
            # can't be bound from worker threads, and fan-out runs
            # children inside a ThreadPoolExecutor.
            import threading
            if threading.current_thread() is not threading.main_thread():
                return
            for sig_name in ("SIGTERM", "SIGHUP"):
                sig = getattr(signal, sig_name, None)
                if sig is None:
                    continue
                try:
                    self._old[sig] = signal.signal(sig, self._handler)
                except (ValueError, OSError):
                    pass

        def __exit__(self, *_: Any) -> None:
            for sig, old in self._old.items():
                try:
                    signal.signal(sig, old)
                except (ValueError, OSError):
                    pass

        def _handler(self, signum: int, _frame: Any) -> None:
            name = signal.Signals(signum).name
            self.autopilot.request_stop(f"halted by {name}")

    def _signal_guard(self) -> "Autopilot._SignalGuard":
        return Autopilot._SignalGuard(self)


# ── pricing lookup helpers ───────────────────────────────────


def _lookup_dollars(model: str, input_tokens: int, output_tokens: int) -> float:
    """Lookup (input_tokens, output_tokens) → USD using the pricing table.

    Imported lazily because the costs module is optional — the Autopilot
    core shouldn't hard-fail just because a caller isn't interested in
    dollar tracking.
    """
    try:
        from shipit_agent.costs.pricing import MODEL_PRICING
    except Exception:       # noqa: BLE001
        return 0.0

    prices = _resolve_pricing(model, MODEL_PRICING)
    if not prices:
        return 0.0

    per_million = 1_000_000.0
    return (
        input_tokens * float(prices.get("input", 0.0)) / per_million
        + output_tokens * float(prices.get("output", 0.0)) / per_million
    )


def _resolve_pricing(model: str, table: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Find a pricing row that best matches a model id.

    Handles Bedrock-style prefixes (``bedrock/anthropic.claude-…``) and
    LiteLLM-style suffixes (``openai/gpt-4o-mini``) by also checking the
    name without the leading provider segment.
    """
    if model in table:
        return table[model]
    # Strip up to two leading provider segments.
    candidate = model
    for _ in range(2):
        if "/" in candidate:
            candidate = candidate.split("/", 1)[1]
            if candidate in table:
                return table[candidate]
    # Substring match as a last resort (e.g. "claude-sonnet-4-20250514" → "claude-sonnet-4").
    for key, row in table.items():
        if key and key in model:
            return row
    return None
