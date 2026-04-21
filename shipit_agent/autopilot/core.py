"""Autopilot — the long-running "keep working until goal is met" runner.

Composes the inner ``GoalAgent`` with budget gates, persistent checkpoints,
and heartbeat telemetry. See :mod:`shipit_agent.autopilot` for the package
overview and ``streaming.py`` for the :meth:`Autopilot.stream` generator.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

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

        usage = BudgetUsage(iterations=int(prior.get("iterations", 0)))
        step_outputs: list[dict[str, Any]] = list(prior.get("step_outputs", []))
        started = time.monotonic()
        last_hb = started
        final_output = str(prior.get("output", ""))
        criteria_met = [False] * len(self.goal.success_criteria)
        halt_reason = ""

        try:
            while True:
                usage.seconds = time.monotonic() - started
                usage.iterations += 1

                exceeded, reason = self.budget.exceeded(usage)
                if exceeded:
                    halt_reason = reason
                    break

                result = self._build_inner_agent().run()
                final_output = getattr(result, "output", final_output) or final_output
                criteria_met = list(getattr(result, "criteria_met", criteria_met))
                usage.tool_calls += self._count_tool_calls(result)
                usage.tokens += self._count_tokens(result)

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
                if self.on_heartbeat and (now - last_hb) >= self.heartbeat_every_seconds:
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
