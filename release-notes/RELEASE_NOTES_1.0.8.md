# SHIPIT Agent 1.0.8 — Five flagship features that beat the competition

**Release date — 2026-05-09**

Five new flagship features. All five reachable from `from shipit_agent import …`.
Both `Agent` AND `DeepAgent` get them. **1527 unit tests (+337 new). 0 regressions.**

---

## What's new

| Feature | One-line | Beats |
| --- | --- | --- |
| **[Structured output with auto-retry](https://docs.shipiit.com/agent/structured-output/)** | Pydantic / JSON Schema results + same-conversation validation retry + streaming partial JSON | LangChain's `OutputFixingParser` (separate LLM call) |
| **[Verifier network](https://docs.shipiit.com/agent/verifier/)** | Cheap LLM vetoes hallucinated tool calls + detects stalling | LangGraph (no per-call gating) |
| **[Episodic memory consolidation](https://docs.shipiit.com/agent/memory-consolidation/)** | Distill conversations → durable facts. Forgetting curve + core-memory promotion | ChatGPT Memories (no decay, no auto-extract) |
| **[Time-travel replay](https://docs.shipiit.com/agent/time-travel-replay/)** | Fork any saved trace from any event. Resume on a fresh agent | LangSmith Playground / Inngest branching (SaaS-only) |
| **[ComputerUseAgent + BrowserAgentTool](https://docs.shipiit.com/agent/computer-use/)** | Drive a browser by showing screenshots to a vision LLM | Devin / Operator (SaaS-only) |

---

## Structured output overhaul

```python
from pydantic import BaseModel
from shipit_agent import Agent

class Movie(BaseModel):
    title: str
    rating: float

agent = Agent(llm=opus_llm)
result = agent.run(
    "Recommend a thriller.",
    output_schema=Movie,
    max_validation_retries=2,
)
print(result.parsed)  # Movie(title='Heat', rating=8.5)
```

- **`Agent.run(output_schema=, max_validation_retries=)`** — validation retry
  inside the same conversation when the first parse fails. No separate fixing LLM.
- **Streaming partial JSON** — `parse_partial_json('{"a": "hel')` → `{'a': 'hel'}`.
- **`StructuredOutput`** — standalone wrapper for one-shot extraction.
- New top-level exports: `StructuredOutput`, `StructuredOutputResult`,
  `parse_partial_json`. New `result.parsed` field on `AgentResult`.

## Verifier network

```python
from shipit_agent import Agent, VerifierNetwork

verifier = VerifierNetwork(llm=haiku_llm, goal="Audit security of merged PRs")

agent = Agent(
    llm=opus_llm,
    tools=[GitHubTool(), GrepTool()],
    verifier=verifier,        # auto-wraps every tool
)
```

- **Pre-tool veto** — verifier sees `{tool_name, args, recent_history}`,
  returns `allow | veto | rewrite`. Vetoed calls become synthetic error
  tool-results so the agent re-plans.
- **Progress check** — after each iteration, scores progress 0-1.
  When a streak of low scores hits the window, `maybe_nudge()` returns a
  "you're stalling" message to inject as a user turn.
- **Confidence-gated** — verdicts below `veto_min_confidence` get downgraded
  to ALLOW.
- **Hard caps + telemetry** — `max_pretool_calls_per_run`,
  `max_progress_calls_per_run`, plus `verifier.stats` for observability.
- New top-level exports: `VerifierNetwork`, `VerifierConfig`, `VerifierVerdict`,
  `PreToolDecision`, `PreToolVerifier`, `ProgressCheck`, `ProgressVerifier`.

## Episodic memory consolidation

```python
from shipit_agent import MemoryConsolidator

c = MemoryConsolidator(llm=cheap_llm)

# After every N turns
c.consolidate(memory=mem, recent_messages=mem.get_conversation_messages())

# Once a day
c.decay(mem.knowledge, half_life_days=14)

# Every turn — top-K facts → system prompt
core = c.core_memory(mem.knowledge, top_k=5)
```

- **`consolidate()`** — LLM distills last conversation into 3-8 durable
  facts with categories (`preference`/`project`/`person`/`goal`).
- **`decay()`** — pure-Python exponential strength decay; prunes facts
  below `forgetting_threshold`.
- **`core_memory()`** — top-K facts ranked by `strength + 0.1·log1p(retrievals)`.
- **`record_retrieval()`** — bump retrieval counters when search returns
  a fact. Frequently-retrieved facts naturally rise to core memory.
- New exports: `MemoryConsolidator`, `DistilledFact`, `ConsolidationResult`.

## Time-travel replay

```python
from shipit_agent.replay import TraceReplayer

replayer = TraceReplayer.from_store(store, "run-2026-05-09-abc")

# Fork before the bad iteration with a tweaked prompt
fork = replayer.fork(at_event=12, edit_user_message="Try a narrower question.")

# Resume on a fresh agent
result = fork.continue_from(agent=Agent(llm=opus_llm))
```

- **Inspect** — `replayer.events`, `event_indices_by_type()`, `messages_at()`,
  `find_user_messages()`.
- **Fork** — `fork(at_event=, edit_user_message=, extra_metadata=)`.
- **Resume** — `checkpoint.continue_from(agent=, **kwargs)`. Agent's history
  is pre-filled with reconstructed messages.
- **Diff** — `diff_traces(left, right)` reports matched events,
  divergence point, type mismatches, and only-in-left/right tails.
  `.to_lines()` for human-readable rendering.
- New exports: `TraceReplayer`, `ReplayCheckpoint`, `ReplayResult`,
  `ForkPoint`, `TraceDiff`, `diff_traces`.

## ComputerUseAgent + BrowserAgentTool

Two patterns shipping together:

### Pattern 1 — standalone

```python
from shipit_agent.computer_use import (
    ComputerUseAgent, PlaywrightBrowserSession,
)

with PlaywrightBrowserSession.launch(headless=True) as browser:
    agent = ComputerUseAgent(
        llm=opus_llm,
        browser=browser,
        goal="Find iPhone 15 Pro starting price.",
    )
    result = agent.run()
```

### Pattern 2 — as a tool inside the main Agent (recommended for production)

```python
from shipit_agent import Agent, VerifierNetwork
from shipit_agent.computer_use import (
    BrowserAgentTool, PlaywrightBrowserSession,
)

browser_tool = BrowserAgentTool(
    llm=opus_llm,
    browser_factory=lambda: PlaywrightBrowserSession.launch(headless=True),
    max_iterations=12,
)

agent = Agent(
    llm=opus_llm,
    tools=[browser_tool, WebSearchTool(), PDFTool()],
    verifier=VerifierNetwork(llm=haiku_llm, goal="Research only — no purchases"),
)

result = agent.run(
    "Find the cheapest direct SFO-JFK flight on May 20 "
    "and summarise the booking page."
)
```

The main agent picks `browser_use` when it's the right tool — same way it
picks `web_search` or `pdf_extract`. The verifier vetoes destructive
browser actions before they fire.

- **Two action emit shapes**: Anthropic native `computer-use` tool block
  + plain-text `ACTION: click 100,200` fallback for any vision LLM.
- **`MockBrowserSession`** — deterministic test double. Records every call.
- **`PlaywrightBrowserSession.launch()`** — production driver. Context-manager
  support. `pip install playwright && playwright install chromium`.
- **Recovery** — when an action raises, the agent surfaces the error back
  to the model as a user message. Production-ready resilience built in.
- **`BrowserAgentTool(share_browser=True)`** — multi-step workflows that
  need persistent browser state.
- New exports: `ComputerUseAgent`, `BrowserAgentTool`, `BrowserSession`,
  `MockBrowserSession`, `PlaywrightBrowserSession`, `ComputerAction`,
  `ComputerUseResult`, `ActionKind`, `ActionRecord`, `parse_action`.

---

## Tests + docs + notebooks

- **+337 unit tests** (1190 → 1527), zero regressions.
- **6 new notebooks** — 54 (structured output), 55 (verifier), 56 (memory
  consolidation), 57 (time-travel replay), 58 (ComputerUseAgent), 59
  (BrowserAgentTool integration).
- **5 new docs pages** under `agent/` with full API reference, configuration
  deep dives, cost analysis, and beat-the-competition tables.
- **Dedicated `/v1.0.8` and `/browser-agent` landing pages** at docs.shipiit.com.
- **Five new top-level component categories** in the docs site nav:
  Structured Output, Verifier Network, Memory Consolidation, Time-Travel
  Replay, ComputerUseAgent (each with its own dropdown menu item).

---

## Compatibility

- All v1.0.7 APIs continue to work unchanged.
- New constructor kwargs on `Agent`: `verifier=` (default `None`).
- New `Agent.run` kwargs: `output_schema=` (already existed; behavior
  upgraded), `max_validation_retries=` (new, default 2).
- New `DeepAgent` kwargs: `verifier=` propagates through to inner Agent.
- `create_deep_agent(verifier=...)` accepted.
- Optional dependencies: install Playwright for `PlaywrightBrowserSession`
  (the package imports it lazily).

---

## Acknowledgements

This release is the result of a focused push on **the four areas where
LangChain, LangGraph, ChatGPT, and the SaaS computer-use products are
weakest**: validation retry, process supervision, memory consolidation,
time-travel debugging, and self-hosted browser automation.

Five flagship features. One pip install. Library-level API the whole way down.
