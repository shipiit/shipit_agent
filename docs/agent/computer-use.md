---
title: ComputerUseAgent (browser automation)
description: Drive a real browser by showing screenshots to a vision-capable LLM. Anthropic's computer-use API works natively; OpenAI / Bedrock / Gemini work via plain-text fallback. Covers form filling, scraping, end-to-end testing, web apps without APIs.
---

# ComputerUseAgent

`ComputerUseAgent` runs a screenshot → reason → act loop:

1. Take a screenshot of the current viewport
2. Show it (plus the goal) to a vision-capable LLM
3. Parse the model's response into a structured `ComputerAction`
4. Execute it on the browser
5. Repeat until the model says `done`

This unlocks every workflow that has no API: booking flights, internal
SaaS, legacy dashboards, multi-step form filling, end-to-end testing
that adapts when the UI shifts. Two action emit-shapes are supported —
**Anthropic's native `computer-use` tool** and a **plain-text fallback**
that works with any vision LLM.

> **TL;DR**
> ```python
> from shipit_agent.computer_use import (
>     ComputerUseAgent, PlaywrightBrowserSession,
> )
>
> with PlaywrightBrowserSession.launch(headless=True) as browser:
>     agent = ComputerUseAgent(llm=opus_llm, browser=browser,
>                              goal="Find iPhone 15 Pro price on apple.com")
>     result = agent.run()
>     print(result.final_text)  # → "iPhone 15 Pro starts at $999"
> ```

---

## Why this matters

Devin, Multi-On, and OpenAI's Operator all ship browser-driving agents
— but as products, not libraries. **shipit's is a library**:

| Product | shipit_agent.ComputerUseAgent |
| --- | --- |
| Devin | Plug into your own agent loop, your own LLM |
| Operator | Self-host, no SaaS dependency |
| Multi-On | Test against a `MockBrowserSession`, no Playwright needed for unit tests |

Use the abstractions. Fork the implementation. Run it on your own infra.

---

## Architecture (10-line summary)

```
                 ┌────────────────────┐
                 │  ComputerUseAgent  │
                 │  ──────────────────│
                 │  goal              │
                 │  llm               │
                 │  browser           │  (BrowserSession protocol)
                 │  max_iterations    │
                 └──────────┬─────────┘
                            │ screenshot + goal
                            ▼
                  ┌─────────────────┐
                  │   vision LLM    │
                  └─────────┬───────┘
                            │ ACTION: click 100,200
                            ▼
                  ┌─────────────────┐
                  │  parse_action() │ → ComputerAction
                  └─────────┬───────┘
                            │ click(100, 200)
                            ▼
                  ┌─────────────────┐
                  │ BrowserSession  │  (Playwright in prod, mock in tests)
                  └─────────────────┘
```

`BrowserSession` is a Protocol with seven methods: `screenshot`, `click`,
`type_text`, `key`, `scroll`, `navigate`, `close`. Any object exposing
those plugs in.

---

## Quick start (offline / testing)

```python
from shipit_agent.computer_use import ComputerUseAgent, MockBrowserSession

class StubLLM:
    def __init__(self, replies): self._r, self._i = replies, 0
    def complete(self, *, messages, **_):
        text, self._i = self._r[self._i], self._i + 1
        return text

llm = StubLLM([
    "I'll start at apple.com.\nACTION: navigate https://apple.com",
    "Navigate to iPhone.\nACTION: click 240,80",
    "Open the 15 Pro page.\nACTION: click 600,400",
    "Found it: $999.\nACTION: done iPhone 15 Pro starts at $999.",
])

agent = ComputerUseAgent(
    llm=llm,
    browser=MockBrowserSession(),
    goal="Find iPhone 15 Pro starting price on apple.com",
    max_iterations=8,
)

result = agent.run()
print(result.status)        # "done"
print(result.final_text)    # "iPhone 15 Pro starts at $999."
print(result.iterations)    # 4
```

The `MockBrowserSession` records every call to `self.calls` for
assertions — perfect for unit-testing computer-use logic without
spawning a real browser.

---

## Quick start (production)

```bash
pip install playwright
playwright install chromium
```

```python
from shipit_agent.computer_use import (
    ComputerUseAgent, PlaywrightBrowserSession,
)

with PlaywrightBrowserSession.launch(
    headless=True,                # set False to watch it run
    viewport_size=(1280, 720),
    start_url="about:blank",
) as browser:
    agent = ComputerUseAgent(
        llm=opus_llm,             # Claude with computer-use beta access
        browser=browser,
        goal="Find the cheapest direct SFO → JFK flight on May 20.",
        max_iterations=15,
    )
    result = agent.run()
    print(result.final_text)
```

The `with` statement guarantees the browser closes on exit (success,
failure, or exception).

---

## Action commands

The model emits one action per turn. Two shapes are accepted; the parser
decides automatically.

### Plain-text (any vision LLM)

```
ACTION: click X,Y           ← left-click at pixel (x, y)
ACTION: type "text"         ← type into the focused element
ACTION: key Enter           ← press a special key
ACTION: scroll DX DY        ← scroll by (dx, dy) pixels
ACTION: scroll 600          ← single int = vertical scroll
ACTION: navigate URL        ← open a URL
ACTION: screenshot          ← re-read current state
ACTION: done <answer>       ← end the run with a final answer
```

The parser tolerates casing, whitespace, surrounding prose, and quoted
or unquoted text arguments. If multiple `ACTION:` lines appear, the
**last** one wins (the model may emit reasoning + action; the action is
what runs).

### Anthropic native computer-use

When the model emits a structured `tool_use` block:

```python
{
  "type": "tool_use",
  "name": "computer",
  "input": {
    "action": "left_click",
    "coordinate": [320, 180],
    "rationale": "Clicking the search icon."
  }
}
```

`parse_action()` pulls fields directly — no string parsing, no
regex-fragility. Same `ComputerAction` shape comes out.

---

## Real-life patterns

### 1. Scrape a price comparison

```python
result = agent.run()  # goal: "find the lowest price for X on these 3 sites"
# Action history shows every navigation + screenshot + click;
# result.final_text has the comparison.
```

### 2. Form filling at scale (with human review)

```python
goal = (
    "Fill the contact form with name='Alice Cooper', "
    "email='alice@example.com', message='Interested in Pro plan.'. "
    "Pause before submitting."
)
result = agent.run()
# Run completes when the agent reaches the 'submit' button.
# The human reviews the screenshot, then clicks for real.
```

Combine with the `AskUserAsyncTool` (a built-in shipit tool) to make
this fully async — the agent saves state, asks the human, resumes.

### 3. End-to-end UI testing

```python
goal = (
    "Sign up for an account with email='test+{ts}@example.com' "
    "and verify the dashboard loads with the welcome banner. "
    "Report PASS or FAIL."
)
result = agent.run()
assert "PASS" in result.final_text
```

Adapts when the UI shifts (no flaky CSS selectors). Failure modes are
captured in `result.action_history` for replay.

### 4. Recovery from failed actions

`ComputerUseAgent` automatically surfaces tool errors back to the model
as user messages:

```python
class FlakyBrowser(MockBrowserSession):
    def click(self, x, y):
        if self._first:
            self._first = False
            raise RuntimeError("Element not visible at (x, y)")
        super().click(x, y)
```

When the click raises, the agent loop catches it, tells the model
*"Your last action failed: <error>. Take a different approach."* and
continues. Production-ready recovery without extra code.

---

## Combining with other features

### + Verifier network (process supervision)
```python
from shipit_agent.verifier import VerifierNetwork

verifier = VerifierNetwork(llm=haiku_llm, goal="Look up prices, no purchases")
# Wrap any tool the agent has access to — the verifier vetoes destructive
# actions (e.g. clicking 'Buy now' when the goal is just to look)
```

### + Time-travel replay
Every screenshot + action is in `result.action_history` already. To fork
a failed run from a specific iteration, swap the screenshot+action
history into a new agent's prompt and resume.

### + Structured output
The `done` action's `final_text` can be JSON; pair with `output_schema=`
on a wrapping `Agent` to type-check it.

---

## Custom browser sessions

Anything quacking like a `BrowserSession` works. Want to drive a
remote VNC bridge? Build a class with seven methods:

```python
class VNCBrowserSession:
    def __init__(self, host: str): self._host = host
    def screenshot(self) -> str:    # base64 PNG
        ...
    def click(self, x, y): ...
    def type_text(self, text): ...
    def key(self, k): ...
    def scroll(self, dx, dy): ...
    def navigate(self, url): ...
    def close(self): ...

agent = ComputerUseAgent(llm=llm, browser=VNCBrowserSession("...:5900"), goal="...")
```

The same pattern works for testing (`MockBrowserSession`), CDP-direct
implementations, or wrappers around remote browser farms.

---

## Tuning

```python
ComputerUseAgent(
    llm=...,
    browser=...,
    goal="...",
    max_iterations=10,                 # safety cap on think-act cycles
    viewport_size=(1280, 720),         # for LLM context
    action_emit_mode="auto",           # "auto" / "anthropic" / "text"
    screenshot_format="png",           # "png" / "jpeg"
)
```

| Setting | Lower means | Higher means |
| --- | --- | --- |
| `max_iterations` | Faster, may not finish | More thorough, more tokens |
| `viewport_size` | Smaller screenshots, less detail | Larger, more detail, more tokens |
| `screenshot_format` | `png`: better text legibility | `jpeg`: smaller payloads |

For **most workflows**, defaults are fine. Bump `max_iterations` for
multi-page workflows (form sequences, e-commerce checkout). Drop to
`(1024, 576)` viewport for cost-sensitive scraping.

---

## Cost analysis

Per agent run with the defaults:
* **Per iteration** — ~5K input tokens (image + prompt + history) + ~100 output
* **10 iterations** — ~50K input + ~1K output tokens
* On Claude 4.5 Sonnet ($3 / $15 per Mtok): **~$0.16 per run**
* On GPT-4o ($2.50 / $10): **~$0.13 per run**
* On Bedrock gpt-oss-120b ($0.15 / $0.60): **~$0.008 per run**

Compare to Devin/Operator subscription pricing ($20-500/month flat).
Self-hosted, you pay only the model bill.

---

## API reference

### `ComputerUseAgent`
```text
ComputerUseAgent(
    *, llm,
    browser: BrowserSession,
    goal: str,
    max_iterations: int = 10,
    viewport_size: tuple[int, int] | None = None,
    action_emit_mode: str = "auto",
    screenshot_format: str = "png",
)
```

| Method | Returns | Notes |
| --- | --- | --- |
| `.run()` | `ComputerUseResult` | Blocking; runs the full loop. |

### `ComputerUseResult`
| Field | Type |
| --- | --- |
| `status` | `"done"` \| `"max_iterations"` \| `"error"` |
| `final_text` | model's `done`-action text |
| `action_history` | list of `ActionRecord` (action + screenshot + iteration) |
| `iterations` | count of think-act cycles |
| `error` | top-level error or `None` |

### `BrowserSession` (Protocol)
| Method | Notes |
| --- | --- |
| `screenshot()` → `str` | Base64-encoded PNG/JPEG of viewport |
| `click(x, y)` | Pixel coords from top-left |
| `type_text(text)` | Type into focused element |
| `key(name)` | `Enter`, `Tab`, `Escape`, `ArrowDown`, etc. |
| `scroll(dx, dy)` | Pixel deltas |
| `navigate(url)` | Open URL |
| `close()` | Tear down |

### `MockBrowserSession`
Records every call to `self.calls` (`list[(method, args)]`). Returns
canned screenshots from a constructor list. Use for tests.

### `PlaywrightBrowserSession`
```text
PlaywrightBrowserSession.launch(
    *, headless=True,
    viewport_size=(1280, 720),
    start_url="about:blank",
) -> PlaywrightBrowserSession  # also context manager
```

### `parse_action(raw) → ComputerAction`
Parse any LLM response shape into a structured action. Pure function,
no IO.

---

## `BrowserAgentTool` — use it as a tool inside the main `Agent`

The killer pattern: your **main `Agent` plans**, and when it needs to drive
a browser it delegates to a sub-`ComputerUseAgent` via a single `browser_use`
tool call.

* The main agent never has to think in pixels.
* The sub-agent never has to plan the larger task.
* Both are observable through the same event stream.
* `browser_use` is just another `Tool` in your toolbox — composes with
  `WebSearchTool`, `PDFTool`, RAG, structured output, and the verifier.

### Quick start

```python
from shipit_agent import Agent, VerifierNetwork
from shipit_agent.computer_use import (
    BrowserAgentTool, PlaywrightBrowserSession,
)

# 1. Build the browser tool — it owns the sub-agent's LLM and browser factory
browser_tool = BrowserAgentTool(
    llm=opus_llm,                                    # vision-capable
    browser_factory=lambda: PlaywrightBrowserSession.launch(headless=True),
    max_iterations=12,
)

# 2. Optional: add a verifier so destructive actions get gated
verifier = VerifierNetwork(llm=haiku_llm, goal="Research only — no purchases.")

# 3. Hand the browser_use tool to your main planning agent
agent = Agent(
    llm=opus_llm,
    tools=[browser_tool, WebSearchTool(), PDFTool()],
    verifier=verifier,
)

# 4. Run a high-level goal — the main agent decides when to call browser_use
result = agent.run(
    "Find the cheapest direct SFO-JFK flight on May 20 "
    "and summarise the booking page."
)
```

### What the model sees

`BrowserAgentTool` exposes a single argument: `goal: str`. The main agent
writes a clear goal in plain English, the sub-agent figures out the
clicks/types/scrolls. Schema:

```json
{
  "type": "object",
  "properties": {
    "goal": {
      "type": "string",
      "description": "What the browser sub-agent should accomplish, in plain English."
    }
  },
  "required": ["goal"]
}
```

### Result shape

When the sub-agent finishes, the parent receives a `ToolOutput` with:

* **`text`** — formatted summary: status + iterations + final answer +
  the last 8 actions taken.
* **`metadata.status`** — `"done"` / `"max_iterations"` / `"error"`
* **`metadata.iterations`** — how many think-act cycles the sub-agent ran
* **`metadata.actions`** — full action history (kind + args + error per step)

Example output text:

```
Browser sub-agent finished (status=done, iterations=4).
Goal: Find the cheapest direct SFO-JFK flight on May 20.

Answer: Cheapest direct is JetBlue B6 1234 at $187, departs 11:30am.

Last actions:
  · iter 0: navigate
  · iter 1: type
  · iter 2: click
  · iter 3: done
```

### `share_browser=True` — multi-step workflows

Default is fresh browser per call. For workflows where state must persist
across calls (logged-in session, shopping cart, multi-page forms), enable
`share_browser=True`:

```python
browser_tool = BrowserAgentTool(
    llm=vision_llm,
    browser_factory=lambda: PlaywrightBrowserSession.launch(headless=False),
    share_browser=True,                              # ← reuse session
)

# Each tool call now operates on the same browser, preserving state
agent.run("Log in to the dashboard with credentials from the vault.")
agent.run("Open the billing page.")
agent.run("Download the latest invoice as a PDF.")

# Always close at the end
browser_tool.close()
```

Trade-off: faster (no browser relaunch) but state leaks between calls —
only enable when the parent agent is aware that browser state persists.

### Custom browser sessions for the parent tool

Anything quacking like a `BrowserSession` works as the factory return
value. For testing, use `MockBrowserSession`:

```python
from shipit_agent.computer_use import BrowserAgentTool, MockBrowserSession

tool = BrowserAgentTool(
    llm=fake_llm,
    browser_factory=lambda: MockBrowserSession(),
)
result = tool.run(goal="testing — no real browser needed")
```

### Why this is more powerful than computer-use as the top-level agent

| Pattern | When to use |
| --- | --- |
| Top-level `ComputerUseAgent` | Single-task workflows where the goal IS to drive the browser. |
| **`Agent` + `BrowserAgentTool`** | **Most production work.** The main agent has multiple capabilities (web_search, PDF, SQL, browser); `browser_use` is just one option among many that it picks based on the task. |
| `Agent` + `BrowserAgentTool` + `VerifierNetwork` | Production at scale. The verifier vetoes destructive browser actions before they fire. |

### See it work

* [Notebook 58 — ComputerUseAgent (standalone)](https://github.com/shipiit/shipit_agent/blob/main/notebooks/58_computer_use_agent.ipynb) — four direct-use patterns
* [Notebook 59 — BrowserAgentTool inside main Agent](https://github.com/shipiit/shipit_agent/blob/main/notebooks/59_browser_agent_tool.ipynb) — three integration patterns

---

## Going deeper

* [Notebook 58 — ComputerUseAgent](https://github.com/shipiit/shipit_agent/blob/main/notebooks/58_computer_use_agent.ipynb) — four real-life examples
* [Notebook 59 — BrowserAgentTool integration](https://github.com/shipiit/shipit_agent/blob/main/notebooks/59_browser_agent_tool.ipynb) — three integration patterns
* [Verifier network](./verifier.md) — gate destructive actions
* [Time-travel replay](./time-travel-replay.md) — debug failed runs by forking from any iteration
