"""Autopilot.stream() — the live-event generator for Claude-Desktop-style UIs.

Yields envelopes as the run progresses so a CLI or TUI can render tool
calls, heartbeats, and milestones in real time. The final yield is
always an ``autopilot.result`` event containing the full
:class:`AutopilotResult` payload.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from .budget import BudgetUsage
from .core import Autopilot
from .critic import CriticVerdict
from .events import coerce_event
from .result import AutopilotResult


def autopilot_stream(
    self: Autopilot,
    run_id: str | None = None,
    *,
    resume: bool = False,
) -> Iterator[dict[str, Any]]:
    """Generator returning ``{"kind": str, **payload}`` dicts per event.

    Event kinds:
      - ``autopilot.run_started``       {"run_id","goal","resuming"}
      - ``autopilot.iteration``          {"iteration","usage","criteria_met","summary"}
      - ``autopilot.tool``               passthrough from inner agent
      - ``autopilot.heartbeat``          {"iteration","usage","criteria_satisfied_count"...}
      - ``autopilot.budget_exceeded``    {"reason","usage"}
      - ``autopilot.criteria_satisfied`` {"criteria_met"}
      - ``autopilot.stream_fallback``    {"error"} — inner stream broke; ran sync
      - ``autopilot.result``             the final AutopilotResult payload
    """
    rid = run_id or f"run-{int(time.time())}"
    if self.checkpoints.exists(rid) and not resume:
        raise FileExistsError(
            f"Checkpoint exists for run_id={rid!r}. Pass resume=True to continue."
        )
    prior = self.checkpoints.load(rid) if resume else {}

    usage = BudgetUsage(iterations=int(prior.get("iterations", 0)))
    step_outputs: list[dict[str, Any]] = list(prior.get("step_outputs", []))
    started = time.monotonic()
    last_hb = started
    halt_reason = ""
    final_output = str(prior.get("output", ""))
    criteria_met = [False] * len(self.goal.success_criteria)

    yield {
        "kind": "autopilot.run_started",
        "run_id": rid,
        "goal": self.goal_dict(),
        "resuming": bool(prior),
    }

    try:
        while True:
            usage.seconds = time.monotonic() - started
            usage.iterations += 1

            exceeded, reason = self.budget.exceeded(usage)
            if exceeded:
                halt_reason = reason
                yield {
                    "kind": "autopilot.budget_exceeded",
                    "reason": reason,
                    "usage": usage.to_dict(),
                }
                break

            inner = self._build_inner_agent()
            result: Any = None

            # Forward inner events if the inner agent supports streaming.
            # A yield-from here is the cleanest way to re-emit the child's
            # events through this outer generator.
            if hasattr(inner, "stream") and callable(inner.stream):
                try:
                    for ev in inner.stream():
                        yield coerce_event(ev, kind_hint="autopilot.tool")
                        result = ev
                except Exception as err:  # noqa: BLE001
                    yield {
                        "kind": "autopilot.stream_fallback",
                        "error": f"{type(err).__name__}: {err}",
                    }
                    result = inner.run()
            else:
                result = inner.run()

            final_output = getattr(result, "output", final_output) or final_output
            criteria_met = list(getattr(result, "criteria_met", criteria_met))
            usage.tool_calls += self._count_tool_calls(result)
            usage.tokens += self._count_tokens(result)

            # Surface artifacts extracted this iteration.
            new_artifacts: list[Any] = []
            if self.artifacts is not None:
                try:
                    new_artifacts = self.artifacts.extract_from_output(
                        final_output, iteration=usage.iterations,
                    )
                except Exception:   # noqa: BLE001
                    new_artifacts = []
                for a in new_artifacts:
                    # Artifact.to_dict() carries its own `kind` ("code",
                    # "markdown", "file"), so we lift it to `artifact_kind`
                    # and keep `kind` reserved for the stream envelope.
                    art_dict = a.to_dict()
                    art_dict["artifact_kind"] = art_dict.pop("kind")
                    yield {"kind": "autopilot.artifact", **art_dict}

            # Critic pass → emit verdict before the iteration event so UIs
            # can render the critic panel alongside the step summary.
            verdict = CriticVerdict()
            if self.critic is not None:
                verdict = self.critic.review(
                    objective=self.goal.objective,
                    criteria=self.goal.success_criteria,
                    output=final_output,
                    fallback_llm=self.llm,
                )
                yield {"kind": "autopilot.critic", **verdict.to_dict()}
                # Only trust flag-flips from a critic that's confident.
                if (
                    any(verdict.criteria_met)
                    and verdict.confidence >= self.critic.confidence_threshold
                ):
                    criteria_met = list(verdict.criteria_met)
                self._stash_critic_suggestions(verdict)

            step_outputs.append({
                "iteration": usage.iterations,
                "status": getattr(result, "goal_status", "unknown"),
                "criteria_met": criteria_met,
                "summary": final_output[:500],
            })
            yield {
                "kind": "autopilot.iteration",
                "iteration": usage.iterations,
                "usage": usage.to_dict(),
                "criteria_met": criteria_met,
                "summary": step_outputs[-1]["summary"],
            }

            now = time.monotonic()
            if (now - last_hb) >= self.heartbeat_every_seconds:
                hb = {
                    "kind": "autopilot.heartbeat",
                    "iteration": usage.iterations,
                    "usage": usage.to_dict(),
                    "criteria_met": criteria_met,
                    "criteria_satisfied_count": sum(1 for c in criteria_met if c),
                    "criteria_total": len(criteria_met),
                }
                yield hb
                if self.on_heartbeat:
                    try: self.on_heartbeat(hb)
                    except Exception: pass
                last_hb = now

            if criteria_met and all(criteria_met):
                halt_reason = "all criteria satisfied"
                yield {"kind": "autopilot.criteria_satisfied", "criteria_met": criteria_met}
                break
            if self.critic is not None and self.critic.should_terminate(verdict):
                halt_reason = "critic confirmed satisfaction"
                yield {"kind": "autopilot.criteria_satisfied", "criteria_met": criteria_met, "by_critic": True}
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
    except Exception as err:    # noqa: BLE001
        halt_reason = f"exception: {type(err).__name__}: {err}"
        self.checkpoints.save(
            rid, goal=self.goal_dict(), usage=usage,
            step_outputs=step_outputs, output=final_output,
        )
        yield {
            "kind": "autopilot.result",
            **_to_dict(self, rid, "failed", criteria_met, usage, final_output, halt_reason, step_outputs),
        }
        return

    self.checkpoints.save(
        rid, goal=self.goal_dict(), usage=usage,
        step_outputs=step_outputs, output=final_output,
    )
    status = self._classify_status(criteria_met)
    yield {
        "kind": "autopilot.result",
        **_to_dict(self, rid, status, criteria_met, usage, final_output, halt_reason, step_outputs),
    }


def _to_dict(
    autopilot: Autopilot,
    run_id: str, status: str, criteria_met: list[bool],
    usage: BudgetUsage, output: str, halt_reason: str,
    step_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the final `autopilot.result` payload, including artifacts +
    the last critic verdict when those hooks were wired."""
    artifacts: list[dict[str, Any]] = []
    if autopilot.artifacts is not None:
        artifacts = [a.to_dict() for a in autopilot.artifacts.all()]
    verdict_dict: dict[str, Any] = {}
    last = getattr(autopilot, "_last_verdict", None)
    if last is not None:
        verdict_dict = last.to_dict()
    return AutopilotResult(
        run_id=run_id, status=status,
        criteria_met=criteria_met,
        iterations=usage.iterations,
        usage=usage.to_dict(),
        output=output, halt_reason=halt_reason,
        step_outputs=step_outputs,
        artifacts=artifacts,
        critic_verdict=verdict_dict,
    ).to_dict()


# Monkey-attach so `autopilot.stream(...)` works on the class.
Autopilot.stream = autopilot_stream  # type: ignore[attr-defined]
