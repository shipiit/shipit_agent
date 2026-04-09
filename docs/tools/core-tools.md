---
title: Core Tools
description: Reference for the core runtime tools — web search, URL fetching, browser automation, semantic tool discovery, human-in-the-loop, and planning.
---

# Core Tools

The runtime essentials. These are the tools you'll attach to almost every shipit-agent.

| Tool | Tool ID | Purpose |
|---|---|---|
| `WebSearchTool` | `web_search` | Search the web with pluggable providers |
| `OpenURLTool` | `open_url` | Fetch a URL with Playwright + urllib fallback |
| `PlaywrightBrowserTool` | `playwright_browse` | Drive a real browser for JS-heavy pages |
| `ToolSearchTool` | `tool_search` | Rank registered tools by relevance |
| `AskUserTool` | `ask_user` | Pause the agent and ask a structured question |
| `HumanReviewTool` | `human_review` | Pause for human approval before continuing |
| `PlannerTool` | `plan_task` | Generate a structured execution plan |

---

## `web_search`

**Class:** `WebSearchTool`
**Module:** `shipit_agent.tools.web_search`
**Tool ID:** `web_search`

Searches the web through a pluggable provider. The default provider is **DuckDuckGo** (no API key, no account, works out of the box). You can swap to Brave, Serper, Tavily, or in-process Playwright by passing a different `provider`.

### When to use

- The agent needs **fresh information** that isn't in its training data
- You want a list of **candidate URLs** to feed into `open_url` next
- You need to **find the canonical source** for a fact before quoting it

### Schema

```json
{
  "name": "web_search",
  "description": "Search the web and return structured search results.",
  "parameters": {
    "type": "object",
    "properties": {
      "query":       { "type": "string", "description": "Search query" },
      "max_results": { "type": "integer", "description": "Max results to return" }
    },
    "required": ["query"]
  }
}
```

### Configuration

```python
from shipit_agent import WebSearchTool

# Default — DuckDuckGo, no key needed
tool = WebSearchTool()

# Brave search (requires API key)
tool = WebSearchTool(provider="brave", api_key="BSA...")

# Serper (Google search wrapper)
tool = WebSearchTool(provider="serper", api_key="...")

# Tavily (LLM-optimized search)
tool = WebSearchTool(provider="tavily", api_key="tvly-...")

# In-process Playwright (no API key, scrapes results — slower)
tool = WebSearchTool(provider="playwright")
```

### Example

```python
from shipit_agent import Agent, WebSearchTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[WebSearchTool(provider="duckduckgo")],
)

result = agent.run("Find the official URL for the Python language website.")
print(result.output)
```

### Output structure

`ToolOutput.text` is a numbered list of results in the form:

```
[1] Title of the result
Snippet of the page content...
URL: https://example.com/page

[2] Another result
...
```

`ToolOutput.metadata` contains:

| Field | Type | Description |
|---|---|---|
| `provider` | str | The search provider used |
| `query` | str | The query as sent |
| `result_count` | int | Number of results returned |
| `results` | list[dict] | Structured results: `{title, url, snippet}` |

### Notes

- DuckDuckGo is **rate-limited** — for production, use Brave or Serper
- Tavily produces the most LLM-friendly results (cleaner snippets) but costs money
- The Playwright provider needs `pip install 'shipit-agent[playwright]'` and a one-time `playwright install chromium`

---

## `open_url`

**Class:** `OpenURLTool`
**Module:** `shipit_agent.tools.open_url`
**Tool ID:** `open_url`

Fetches a URL and returns clean text. Uses **in-process Playwright (Chromium)** as the primary path so it handles JS-rendered pages, anti-bot 503s, and modern TLS. Falls back to stdlib `urllib` if Playwright isn't installed.

**Zero third-party HTTP libraries** — no `httpx`, no `requests`, no `beautifulsoup4`. Just Playwright and the standard library.

### When to use

- After `web_search` identified a likely source — fetch it for the actual content
- The agent needs the **exact text** of a specific page, not search snippets
- The page is JS-rendered or behind anti-bot protection

### Schema

```json
{
  "name": "open_url",
  "parameters": {
    "type": "object",
    "properties": {
      "url":       { "type": "string", "description": "URL to open" },
      "max_chars": { "type": "number", "description": "Optional max output length" }
    },
    "required": ["url"]
  }
}
```

### Configuration

```python
from shipit_agent import OpenURLTool

tool = OpenURLTool(
    timeout=30.0,                    # seconds before fetch aborts
    max_chars=4000,                  # truncate output (LLM context savings)
    user_agent="Mozilla/5.0 ...",    # custom UA — defaults to a realistic Chrome string
    headless=True,                   # set False to see the browser window during dev
    wait_until="domcontentloaded",   # or "load", "networkidle"
)
```

### Example

```python
from shipit_agent import Agent, OpenURLTool, WebSearchTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[WebSearchTool(), OpenURLTool()],
)

result = agent.run(
    "Find the official Python downloads page and tell me the latest version."
)
print(result.output)
```

### Output structure

`ToolOutput.text` is the cleaned page text, truncated to `max_chars`.

`ToolOutput.metadata` contains:

| Field | Type | Description |
|---|---|---|
| `url` | str | The URL requested |
| `final_url` | str | The URL after redirects |
| `fetch_method` | str | `"playwright"` or `"urllib"` |
| `status_code` | int | HTTP status code |
| `title` | str | Page title from `<title>` |
| `max_chars` | int | The truncation limit applied |
| `warnings` | list[str] | Non-fatal warnings (e.g. "playwright failed, fell back to urllib") |
| `error` | str | Set only on hard failure (still returns ToolOutput, never raises) |

### Notes

- **Errors never raise out of the tool.** The tool always returns a `ToolOutput` — even on hard failure — so the runtime's tool-pairing invariant stays intact
- Playwright takes ~2-3s to boot Chromium on first call, then is fast for subsequent calls within the same tool invocation
- For faster batch fetching across many URLs, consider running `open_url` calls in parallel via `asyncio.gather` or use `playwright_browse` directly

---

## `playwright_browse`

**Class:** `PlaywrightBrowserTool`
**Module:** `shipit_agent.tools.playwright_browser`
**Tool ID:** `playwright_browse`

Drives a real headless Chromium browser for pages that need full JavaScript execution, interaction, or anti-bot bypass that `open_url`'s simpler fetch can't handle.

### When to use

- The page is a **single-page application** that loads content via XHR/fetch after initial render
- You need to **interact** with the page (click, type, scroll) before reading content
- `open_url` returns empty content because the page is JS-only
- You need to capture data that only appears after a delay

### Schema

```json
{
  "name": "playwright_browse",
  "description": "Use Playwright to open a page and return the rendered text content.",
  "parameters": {
    "type": "object",
    "properties": {
      "url":       { "type": "string" },
      "wait_for":  { "type": "string", "description": "CSS selector to wait for before extracting" },
      "max_chars": { "type": "number" }
    },
    "required": ["url"]
  }
}
```

### Configuration

```python
from shipit_agent import PlaywrightBrowserTool

tool = PlaywrightBrowserTool(
    headless=True,
    timeout=30.0,
    user_agent="Mozilla/5.0 ...",
    viewport={"width": 1280, "height": 800},
)
```

### Notes

- Requires `pip install 'shipit-agent[playwright]'` + `playwright install chromium`
- Slower than `open_url` (~3-5s per call) — only use when needed
- For most fetching needs, `open_url` is the better default since it has the same Playwright primary path with a graceful urllib fallback

---

## `tool_search`

**Class:** `ToolSearchTool`
**Module:** `shipit_agent.tools.tool_search`
**Tool ID:** `tool_search`

Ranks every currently-registered tool by relevance to a plain-language query. Solves the **token bloat** and **tool hallucination** problems that hit any agent with 15+ tools attached.

[**See the dedicated tool_search guide →**](../guides/tool-search.md)

### When to use

- Your agent has 15+ tools attached and you want it to discover the right one before calling
- You're getting tool hallucinations (model invents tool names)
- You want to reduce per-turn token usage by not shipping the full schema catalog

### Schema

```json
{
  "name": "tool_search",
  "parameters": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "What you're trying to do, in plain language" },
      "limit": { "type": "integer", "description": "Max results (1-10, default 5)" }
    },
    "required": ["query"]
  }
}
```

### Scoring

```
score = SequenceMatcher(query, haystack).ratio() + 0.12 × token_hits
```

Pure stdlib, no embeddings. See the [tool_search guide](../guides/tool-search.md#how-it-works) for the full algorithm.

### Configuration

```python
ToolSearchTool(
    max_limit=10,        # hard cap on results
    default_limit=5,     # default when limit not specified
    token_bonus=0.12,    # weight for exact-token hits in scoring
)
```

---

## `ask_user`

**Class:** `AskUserTool`
**Module:** `shipit_agent.tools.ask_user`
**Tool ID:** `ask_user`

Pauses the agent and **asks the user a structured question**. Emits an `interactive_request` event so your UI can show a prompt and collect input before resuming.

### When to use

- The task is ambiguous and needs clarification
- The agent needs the user to **make a choice** between options
- You want to confirm a destructive action before executing it

### Schema

```json
{
  "name": "ask_user",
  "parameters": {
    "type": "object",
    "properties": {
      "question":  { "type": "string", "description": "What to ask the user" },
      "context":   { "type": "string", "description": "Optional context shown alongside the question" },
      "options":   { "type": "array",  "description": "Optional list of choices" }
    },
    "required": ["question"]
  }
}
```

### Behavior

When called, returns a `ToolOutput` with `metadata.interactive=True`. The runtime emits an `interactive_request` event with:

```python
{
    "kind": "ask_user",
    "payload": {
        "question": "What format do you want?",
        "context": "Choose carefully — this affects how the report is generated.",
        "options": [{"label": "PDF"}, {"label": "Markdown"}, {"label": "JSON"}],
    }
}
```

Your UI catches this event, renders a prompt, collects the user's response, and feeds it back into the next turn. See the [streaming guide](../guides/streaming.md) for the full event pattern.

### Example

```python
from shipit_agent import Agent, AskUserTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[AskUserTool()],
)

for event in agent.stream("Generate a report for me — but ask me which format I want first."):
    if event.type == "interactive_request":
        print("Agent is asking:", event.payload["payload"]["question"])
        # Collect input from your UI here, then feed back into the next run
        break
```

---

## `human_review`

**Class:** `HumanReviewTool`
**Module:** `shipit_agent.tools.human_review`
**Tool ID:** `human_review`

Pauses the agent and **requests human approval** before taking a risky action. Like `ask_user`, but specifically for go/no-go decisions on destructive operations.

### When to use

- The agent is about to **delete files**, **send messages**, or **call paid APIs**
- A tool output looks suspicious and you want a human to verify
- You want a **mandatory checkpoint** before continuing a long-running workflow

### Schema

```json
{
  "name": "human_review",
  "parameters": {
    "type": "object",
    "properties": {
      "summary": { "type": "string", "description": "What you're about to do, in one sentence" },
      "details": { "type": "string", "description": "Full context for the human reviewer" },
      "risk":    { "type": "string", "enum": ["low", "medium", "high"] }
    },
    "required": ["summary"]
  }
}
```

### Behavior

Same interactive-event pattern as `ask_user`. Emits `interactive_request` with `kind="human_review"`. Your UI shows a confirmation dialog with the summary, details, and a risk badge, and the user clicks Approve / Deny.

---

## `plan_task`

**Class:** `PlannerTool`
**Module:** `shipit_agent.tools.planner`
**Tool ID:** `plan_task`

Generates a **structured execution plan** with ordered steps, risks, and checkpoints before the main work begins.

### When to use

- The task has **multiple steps** that need careful sequencing
- You want the agent to **think before acting** for non-trivial work
- A human reviewer wants to see the plan before execution starts

### When NOT to use

- Simple single-step tasks (the planner adds overhead and can confuse small models)
- Research tasks where the model should call tools immediately — see the [research example](https://github.com/shipiit/shipit_agent/blob/main/examples/04_research_agent.py) for how to disable auto-planning

### Auto-planning

The runtime can call `plan_task` automatically when `RouterPolicy.should_plan()` matches the prompt (long prompts or those containing keywords like "plan", "research", "task"). To disable:

```python
from shipit_agent.policies import RouterPolicy

agent.router_policy = RouterPolicy(auto_plan=False)
```

### Schema

```json
{
  "name": "plan_task",
  "parameters": {
    "type": "object",
    "properties": {
      "goal":        { "type": "string", "description": "Desired end state" },
      "constraints": { "type": "array",  "description": "Optional constraints" }
    },
    "required": ["goal"]
  }
}
```

### Output

A markdown document with:

```
Goal: <your goal>
Plan:
1. Clarify the target output and inputs.
2. Select the right tools and gather evidence.
3. Execute the task in small verifiable steps.
4. Verify the result against constraints.
5. Return the final deliverable and note any residual risks.
```

The runtime injects this output as a **`user`-role context message** in the conversation history (NOT as a `tool`-role result), which is why Bedrock's tool-pairing API doesn't reject the run. See [architecture](../reference/architecture.md#1-tool-useresult-pairing).

### Notes

- The planner is intentionally a **scaffold**, not an LLM call. It produces a deterministic outline that the LLM can fill in or override
- For richer plans, override the `prompt` constructor kwarg or build a custom Tool subclass

---

## Next: [Reasoning helpers →](reasoning-helpers.md)
