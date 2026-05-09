"""ComputerUseAgent — screenshot → reason → act loop.

Drives a browser (Playwright in production, a mock in tests) by
showing screenshots to a vision-capable LLM and parsing structured
action commands back from the model.

Two action-emit shapes are supported:

1. **Anthropic native computer-use tool calls** — the model emits a
   ``tool_use`` block with ``name=="computer"`` and structured
   ``input``. The parser pulls the action straight from the structured
   data — no string parsing needed.

2. **Plain-text fallback** — the model emits lines like
   ``ACTION: click 320,180`` or ``ACTION: type "hello"``. Use this for
   non-Anthropic models that don't have a native computer-use mode.

Quick start::

    from shipit_agent.computer_use import (
        ComputerUseAgent, MockBrowserSession,
    )

    browser = MockBrowserSession()  # swap PlaywrightBrowserSession in prod
    agent = ComputerUseAgent(
        llm=my_llm,
        browser=browser,
        goal="Find the price of an iPhone 15 Pro on apple.com",
        max_iterations=10,
    )
    result = agent.run()
    print(result.final_text)
    print(f"executed {len(result.action_history)} actions")

Production setup::

    pip install playwright
    playwright install chromium

    from shipit_agent.computer_use import (
        ComputerUseAgent, PlaywrightBrowserSession,
    )

    with PlaywrightBrowserSession.launch(headless=True) as browser:
        agent = ComputerUseAgent(llm=opus_llm, browser=browser, goal="...")
        result = agent.run()
"""

from __future__ import annotations

from .browser_session import (
    BrowserSession,
    MockBrowserSession,
    PlaywrightBrowserSession,
)
from .browser_tool import BrowserAgentTool
from .computer_use_agent import ComputerUseAgent
from .models import (
    ActionKind,
    ActionRecord,
    ComputerAction,
    ComputerUseResult,
)
from .parser import parse_action

__all__ = [
    "ActionKind",
    "ActionRecord",
    "BrowserAgentTool",
    "BrowserSession",
    "ComputerAction",
    "ComputerUseAgent",
    "ComputerUseResult",
    "MockBrowserSession",
    "PlaywrightBrowserSession",
    "parse_action",
]
