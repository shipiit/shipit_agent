"""Adapter that exposes a ``ComputerUseAgent`` as a regular ``Tool``.

This is the killer pattern — your main ``Agent`` plans, and when it
needs to drive a browser it delegates to a sub-`ComputerUseAgent` via
a single ``browser_use`` tool call. The main agent never has to think
in pixels; the sub-agent never has to plan the larger task.

Example::

    from shipit_agent import Agent
    from shipit_agent.computer_use import (
        BrowserAgentTool, PlaywrightBrowserSession,
    )

    browser_tool = BrowserAgentTool(
        llm=vision_llm,                          # the sub-agent's LLM
        browser_factory=lambda: PlaywrightBrowserSession.launch(headless=True),
        max_iterations=12,
    )

    agent = Agent(
        llm=opus_llm,                            # main agent
        tools=[browser_tool, WebSearchTool()],
    )

    result = agent.run(
        "Find the cheapest direct SFO-JFK flight on May 20 "
        "and summarise the booking page."
    )

The main agent will call ``browser_use(goal=...)`` once or twice; each
call spawns a ``ComputerUseAgent``, runs it to completion, and returns
the final text plus a digest of actions taken.
"""

from __future__ import annotations

from typing import Any, Callable

from .browser_session import BrowserSession
from .computer_use_agent import ComputerUseAgent


_DEFAULT_DESCRIPTION = (
    "Drive a real browser to accomplish a goal that requires reading and "
    "interacting with web pages: clicking, typing, scrolling, navigation. "
    "Use when the data isn't reachable via a public API or static fetch. "
    "Pass a single ``goal`` string describing what to accomplish; the tool "
    "runs an autonomous screenshot → reason → act loop and returns the "
    "final answer plus a summary of actions taken."
)

_DEFAULT_PROMPT = (
    "Use this tool ONLY for goals that require browser interaction "
    "(filling forms, navigating multi-page flows, scraping JS-heavy "
    "sites). For simple URL fetches use a static fetch tool instead — "
    "browser_use is more expensive."
)


class BrowserAgentTool:
    """Wrap a ``ComputerUseAgent`` so it can be used as a tool by another Agent.

    Conforms to the shipit ``Tool`` protocol: ``name``, ``description``,
    ``schema()``, ``run(context, **kwargs)``.

    Args:
        llm: the LLM used by the inner ``ComputerUseAgent``. Vision-capable
            recommended (Anthropic Claude with computer-use beta is ideal).
        browser_factory: callable returning a fresh ``BrowserSession`` per
            invocation. The default lambda assumes Playwright is installed
            and uses headless Chromium. Override for testing or custom
            browser plumbing.
        name: tool name as the parent agent sees it. Defaults to ``"browser_use"``.
        description: model-facing description of the tool.
        max_iterations: per-invocation cap. The parent agent can't
            override this; it's a hard safety limit on browser cost.
        share_browser: when True, reuses one ``BrowserSession`` across
            calls. Faster (no relaunch) but state leaks between invocations.
            Default False — fresh browser per call.
    """

    def __init__(
        self,
        *,
        llm: Any,
        browser_factory: Callable[[], BrowserSession] | None = None,
        name: str = "browser_use",
        description: str = _DEFAULT_DESCRIPTION,
        prompt_instructions: str = _DEFAULT_PROMPT,
        max_iterations: int = 10,
        share_browser: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = ""
        self.prompt_instructions = prompt_instructions
        self._llm = llm
        self._browser_factory = browser_factory or _default_playwright_factory
        self._max_iterations = max_iterations
        self._share_browser = share_browser
        self._shared_browser: BrowserSession | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "What the browser sub-agent should accomplish, "
                        "in plain English. Be specific about what to extract or do."
                    ),
                },
            },
            "required": ["goal"],
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        goal = str(kwargs.get("goal", "")).strip()
        if not goal:
            return _make_output(
                text="[browser_use] error: no `goal` argument provided.",
                metadata={"error": "missing-goal"},
            )

        browser = self._acquire_browser()
        try:
            sub_agent = ComputerUseAgent(
                llm=self._llm,
                browser=browser,
                goal=goal,
                max_iterations=self._max_iterations,
            )
            result = sub_agent.run()
        finally:
            if not self._share_browser:
                try:
                    browser.close()
                except Exception:
                    pass

        # Format the sub-agent's outcome for the parent agent
        text = _format_for_parent(goal, result)
        metadata = {
            "tool": self.name,
            "status": result.status,
            "iterations": result.iterations,
            "actions": [
                {
                    "iteration": a.iteration,
                    "kind": a.action.kind.value,
                    "args": a.action.args,
                    "error": a.error,
                }
                for a in result.action_history
            ],
        }
        if result.error:
            metadata["error"] = result.error
        return _make_output(text=text, metadata=metadata)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _acquire_browser(self) -> BrowserSession:
        if self._share_browser:
            if self._shared_browser is None:
                self._shared_browser = self._browser_factory()
            return self._shared_browser
        return self._browser_factory()

    def close(self) -> None:
        """Release the shared browser if one is held."""
        if self._shared_browser is not None:
            try:
                self._shared_browser.close()
            except Exception:
                pass
            self._shared_browser = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_playwright_factory() -> BrowserSession:
    from .browser_session import PlaywrightBrowserSession

    return PlaywrightBrowserSession.launch(headless=True)


def _format_for_parent(goal: str, result: Any) -> str:
    parts = [f"Browser sub-agent finished (status={result.status}, "
             f"iterations={result.iterations})."]
    parts.append(f"Goal: {goal}")
    if result.final_text:
        parts.append(f"\nAnswer: {result.final_text}")
    elif result.error:
        parts.append(f"\nError: {result.error}")
    if result.action_history:
        action_summary = []
        for a in result.action_history[-8:]:
            piece = f"  · iter {a.iteration}: {a.action.kind.value}"
            if a.error:
                piece += f" (failed: {a.error[:80]})"
            action_summary.append(piece)
        parts.append(
            "\nLast actions:\n" + "\n".join(action_summary)
        )
    return "\n".join(parts)


def _make_output(*, text: str, metadata: dict[str, Any]) -> Any:
    """Return a ToolOutput-shaped object. Falls back to a duck-type if the
    tools package isn't importable (keeps this module standalone)."""
    try:
        from shipit_agent.tools.base import ToolOutput

        return ToolOutput(text=text, metadata=metadata)
    except Exception:
        class _Out:
            __slots__ = ("text", "metadata")

            def __init__(self) -> None:
                self.text = text
                self.metadata = metadata

        return _Out()


__all__ = ["BrowserAgentTool"]
