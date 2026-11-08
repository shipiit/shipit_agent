"""ComputerUseAgent's streaming loop: screenshot, model step, action."""

from __future__ import annotations

from typing import Any

from .cua_support import SYSTEM_PROMPT, _error_result
from .models import (
    ActionKind,
    ActionRecord,
    ComputerUseResult,
)
from .parser import parse_action


class _ComputerUseStream:
    """ComputerUseAgent's streaming loop: screenshot, model step, action."""

    def stream(self):
        """Yield live :class:`AgentEvent`s while driving the browser.

        Same loop as :meth:`run`, but observable — each iteration emits
        ``step_started``, ``tool_called`` (the action the model chose),
        ``tool_completed`` / ``tool_failed`` (with ``duration_ms``), and a
        final ``run_completed``. The events use the standard shapes, so
        ``StreamRenderer`` / ``format_event_line`` render browser actions
        as live tool cards::

            renderer = StreamRenderer(style="rich")
            for event in agent.stream():
                renderer.feed(event)

        The generator's return value is the :class:`ComputerUseResult`
        (``run()`` drains the stream and returns it).
        """
        import time as _time

        from shipit_agent.core.models import AgentEvent

        history: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Goal: {self.goal}"},
        ]
        action_history: list[ActionRecord] = []

        def _done_event(result: ComputerUseResult) -> AgentEvent:
            return AgentEvent(
                type="run_completed",
                message=f"Computer use finished: {result.status}",
                payload={
                    "output": result.final_text or f"[{result.status}]",
                    "content": result.final_text,
                    "status": result.status,
                    "iterations": result.iterations,
                },
            )

        yield AgentEvent(
            type="run_started",
            message=f"Computer use started: {self.goal[:80]}",
            payload={"goal": self.goal},
        )

        for i in range(self.max_iterations):
            yield AgentEvent(
                type="step_started",
                message=f"Iteration {i + 1}",
                payload={"iteration": i},
            )
            try:
                screenshot_b64 = self.browser.screenshot()
            except Exception as exc:
                result = _error_result(
                    action_history, iterations=i, error=f"screenshot failed: {exc}"
                )
                yield _done_event(result)
                return result

            history.append(self._user_message_with_screenshot(screenshot_b64))

            try:
                response = self.llm.complete(messages=history)
            except Exception as exc:
                result = _error_result(
                    action_history, iterations=i, error=f"llm call failed: {exc}"
                )
                yield _done_event(result)
                return result

            action = parse_action(response)
            history.append(self._assistant_message(response))

            record = ActionRecord(
                action=action, screenshot_b64=screenshot_b64, iteration=i
            )
            call_id = f"cu-{i}"

            if action.kind == ActionKind.DONE:
                action_history.append(record)
                result = ComputerUseResult(
                    status="done",
                    final_text=action.args.get("final_text", ""),
                    action_history=action_history,
                    iterations=i + 1,
                )
                yield _done_event(result)
                return result

            yield AgentEvent(
                type="tool_called",
                message=f"Browser action: {action.kind.value}",
                payload={
                    "tool": f"browser.{action.kind.value}",
                    "call_id": call_id,
                    "arguments": dict(action.args),
                    "iteration": i,
                },
            )
            started = _time.perf_counter()
            try:
                self._execute(action)
            except Exception as exc:
                record.error = str(exc)
                action_history.append(record)
                yield AgentEvent(
                    type="tool_failed",
                    message=f"Browser action failed: {action.kind.value}",
                    payload={
                        "tool": f"browser.{action.kind.value}",
                        "call_id": call_id,
                        "error": str(exc),
                        "iteration": i,
                        "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
                    },
                )
                # Surface the error back to the model so it can recover
                history.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your last action failed: {exc}. "
                            "Take a different approach."
                        ),
                    }
                )
                continue

            action_history.append(record)
            yield AgentEvent(
                type="tool_completed",
                message=f"Browser action done: {action.kind.value}",
                payload={
                    "tool": f"browser.{action.kind.value}",
                    "call_id": call_id,
                    "output": self._describe_action(action),
                    "iteration": i,
                    "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
                },
            )

        result = ComputerUseResult(
            status="max_iterations",
            final_text="",
            action_history=action_history,
            iterations=self.max_iterations,
        )
        yield _done_event(result)
        return result
