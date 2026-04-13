"""Unified notification manager with hook integration.

:class:`NotificationManager` dispatches :class:`Notification` objects to
one or more :class:`Notifier` channels and can wire itself into
:class:`AgentHooks` for automatic lifecycle notifications.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from shipit_agent.hooks import AgentHooks

from .base import Notification, Notifier, SEVERITY_ORDER
from .templates import DEFAULT_TEMPLATES, render_template

logger = logging.getLogger(__name__)


class NotificationManager:
    """Unified notification manager that dispatches to multiple channels.

    Integrates with :class:`AgentHooks` to automatically send
    notifications on agent lifecycle events.  Supports custom templates,
    filtering by severity, and batch delivery.

    Example::

        manager = NotificationManager([
            SlackNotifier(webhook_url="https://hooks.slack.com/..."),
            DiscordNotifier(webhook_url="https://discord.com/api/webhooks/..."),
            TelegramNotifier(bot_token="...", chat_id="..."),
        ])

        agent = Agent.with_builtins(llm=llm, hooks=manager.as_hooks())

    Args:
        notifiers:    List of notification channel implementations.
        templates:    Optional dict mapping event names to format strings.
                      Falls back to :data:`DEFAULT_TEMPLATES`.
        min_severity: Minimum severity level required to dispatch a
                      notification.  One of ``"info"``, ``"warning"``,
                      ``"error"``, ``"critical"``.
        events:       If provided, only these event names will be
                      dispatched.  ``None`` means all events pass.
    """

    def __init__(
        self,
        notifiers: list[Notifier],
        templates: dict[str, str] | None = None,
        min_severity: str = "info",
        events: list[str] | None = None,
    ) -> None:
        self._notifiers = list(notifiers)
        self._templates = {**DEFAULT_TEMPLATES, **(templates or {})}
        self._min_severity = min_severity
        self._events = set(events) if events else None

        # Track run start time so we can report duration.
        self._run_start: float | None = None
        self._agent_name: str = "agent"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def notify(self, notification: Notification) -> dict[str, bool]:
        """Send *notification* to all registered channels.

        Returns a mapping of ``{notifier_name: success}``.
        """
        if not self._should_notify(notification):
            return {}

        results: dict[str, bool] = {}
        for notifier in self._notifiers:
            try:
                ok = await notifier.send(notification)
            except Exception:
                logger.exception(
                    "Notifier '%s' raised during send", notifier.name
                )
                ok = False
            results[notifier.name] = ok

        return results

    def notify_sync(self, notification: Notification) -> dict[str, bool]:
        """Synchronous wrapper for :meth:`notify`.

        Creates a new event loop if none is running, otherwise schedules
        the coroutine on the existing loop via a background thread.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We are inside an async context — run in a new thread to
            # avoid blocking the loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.notify(notification))
                return future.result(timeout=30)

        return asyncio.run(self.notify(notification))

    def as_hooks(self, agent_name: str = "agent") -> AgentHooks:
        """Create :class:`AgentHooks` that auto-notify on agent events.

        The hooks capture ``run_started`` (inferred from the first LLM
        call), ``run_completed`` (via ``on_after_llm``), and
        ``tool_failed`` (via ``on_after_tool``).

        Args:
            agent_name: Human-readable agent name used in templates.
        """
        self._agent_name = agent_name
        hooks = AgentHooks()

        # -- before LLM: emit run_started on the first call -----------
        def _before_llm(messages: list[Any], tools: list[Any]) -> None:
            if self._run_start is None:
                self._run_start = time.monotonic()
                prompt_preview = ""
                # Try to extract the last user message as a preview.
                for msg in reversed(messages):
                    content = (
                        msg.content if hasattr(msg, "content") else str(msg)
                    )
                    if content:
                        prompt_preview = content[:120]
                        break

                tpl = self._templates.get("run_started", "{agent} started")
                rendered = render_template(
                    tpl, agent=agent_name, prompt_preview=prompt_preview
                )

                note = Notification(
                    event="run_started",
                    title=f"{agent_name} — Run Started",
                    message=rendered,
                    severity="info",
                    metadata={"agent": agent_name},
                )
                self.notify_sync(note)

        hooks.on_before_llm(_before_llm)

        # -- after LLM: emit run_completed ---------------------------
        def _after_llm(response: Any) -> None:
            duration = "n/a"
            if self._run_start is not None:
                elapsed = time.monotonic() - self._run_start
                duration = f"{elapsed:.1f}s"

            # Try to extract output preview and cost from the response.
            output_preview = ""
            cost = "n/a"
            if hasattr(response, "content"):
                output_preview = str(response.content)[:120]
            if hasattr(response, "usage"):
                cost = str(getattr(response.usage, "total_tokens", "n/a")) + " tokens"

            tpl = self._templates.get(
                "run_completed", "{agent} completed in {duration}"
            )
            rendered = render_template(
                tpl,
                agent=agent_name,
                duration=duration,
                cost=cost,
                output_preview=output_preview,
            )

            note = Notification(
                event="run_completed",
                title=f"{agent_name} — LLM Call Completed",
                message=rendered,
                severity="info",
                metadata={
                    "agent": agent_name,
                    "duration": duration,
                    "cost": cost,
                },
            )
            self.notify_sync(note)

        hooks.on_after_llm(_after_llm)

        # -- after tool: detect failures ------------------------------
        def _after_tool(name: str, result: Any) -> None:
            # Determine if the tool call failed by checking for common
            # error indicators on the result object.
            error_msg: str | None = None

            if hasattr(result, "metadata"):
                meta = result.metadata if isinstance(result.metadata, dict) else {}
                if meta.get("error"):
                    error_msg = str(meta["error"])

            if hasattr(result, "output") and result.output.startswith("Error"):
                error_msg = result.output[:200]

            if error_msg is None:
                return  # success — nothing to notify

            tpl = self._templates.get(
                "tool_failed", "{agent} tool '{tool}' failed: {error}"
            )
            rendered = render_template(
                tpl, agent=agent_name, tool=name, error=error_msg
            )

            note = Notification(
                event="tool_failed",
                title=f"{agent_name} — Tool Failed",
                message=rendered,
                severity="error",
                metadata={
                    "agent": agent_name,
                    "tool": name,
                    "error": error_msg,
                },
            )
            self.notify_sync(note)

        hooks.on_after_tool(_after_tool)

        return hooks

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _should_notify(self, notification: Notification) -> bool:
        """Check severity and event filters before dispatching."""
        # Event filter.
        if self._events and notification.event not in self._events:
            return False

        # Severity filter.
        note_level = SEVERITY_ORDER.get(notification.severity, 0)
        min_level = SEVERITY_ORDER.get(self._min_severity, 0)
        return note_level >= min_level
