# Tool Search & Discovery

When an agent has more than a handful of tools, two problems appear:

1. **Token bloat** — every turn ships the full tool catalog to the LLM.
2. **Tool hallucination** — similar tool names get confused and the model invents ones that don't exist.

SHIPIT solves both with progressive discovery: `ToolSearchTool` finds the
capability and `CallToolTool` invokes one hidden tool through the normal
permission, guardrail, approval, retry, trace, and streaming pipeline.

## How it works

The agent calls `tool_search(query="...", limit=5)` with a plain-language description of what it wants to do. The tool ranks every currently-registered tool by relevance and returns the top matches with names, descriptions, usage hints, and scores. Before invoking a hidden capability it requests `detail="schema"`, then passes the exact name and arguments to `call_tool`.

This happens automatically when a plain `Agent(tools=[...], mcps=[...])` has
more than 12 tools or any attached MCP server. Small agents keep their schemas
directly visible. No `with_builtins()` call is required.

Remote MCP startup is deferred too. An unrelated answer makes no MCP transport
request. When the model searches for a capability, SHIPIT first ranks known
local tools; a strong local match stays local. If no local capability fits, or
the query explicitly names an attached server, SHIPIT initializes only the
needed deferred MCP catalog and runs `tools/list`. It performs `tools/call`
only after the model selects a discovered capability.

```python
agent = Agent(
    llm=llm,
    tools=my_large_tool_catalog,
    mcps=[github_mcp, database_mcp],
    tool_context_mode="auto",  # default
)
```

Set `tool_context_mode="full"` only when you deliberately want every schema
sent to the model on every step.

Progressive discovery is not the same as programmatic code mode. Automatic
lazy routing exposes only `tool_search` and `call_tool`; it does not give every
model an `execute_code` tool. Set `code_mode=True` explicitly when the selected
model is reliable at composing multiple tools in code. This separation keeps a
large catalog cheap without forcing weaker models through a code-generation
path they may not handle well.

The runtime also blocks repeated identical failures, compacts pathological
repeated model output before it enters history, and can recover common textual
tool-call fallbacks. Recovery is schema-gated: the tool must be registered for
the run and supplied arguments must match its declaration.

Discovery is preparation, not task completion. If `tool_search` finds a
capability but the model stops without invoking anything, SHIPIT continues the
loop once with a deterministic execution reminder. This does not make another
review-model call. A genuine catalog question such as "Which tool can query
logs?" is allowed to finish after discovery.

Transport failures use a separate turn-scoped circuit breaker. A connection
refusal, connect timeout, DNS failure, or unreachable network marks only that
tool unavailable for the current run. Later calls with different arguments are
blocked immediately because a new query cannot repair the endpoint. Query,
authentication, and downstream-data-source errors do not open the circuit.
Set `transport_circuit_breaker=False` only for unusual tools that dynamically
change endpoints between calls.

### Scoring algorithm

Pure stdlib, no embeddings, no external APIs:

```
score = SequenceMatcher(query, haystack).ratio() + 0.12 × token_hits
```

Where:

- `haystack` = lowercased concatenation of each tool's `name + description + prompt_instructions`
- `SequenceMatcher.ratio()` = fuzzy-similarity ratio in `[0.0, 1.0]`
- `token_hits` = number of query words that appear literally in the haystack
- `0.12` = per-hit bonus (configurable via `token_bonus`)

Results below `score = 0.05` are filtered as noise. Tie-broken by insertion order.

## Usage

```python
from shipit_agent import Agent, ToolSearchTool
from shipit_agent.llms import OpenAIChatLLM

# ToolSearchTool is included in Agent.with_builtins automatically
agent = Agent.with_builtins(llm=OpenAIChatLLM(model="gpt-4o-mini"))

result = agent.run(
    "Use tool_search to find the right tool for fetching a specific URL, "
    "then call that tool on https://example.com"
)
```

The model will call:

```json
{"name": "tool_search", "arguments": {"query": "fetch a specific URL", "limit": 3}}
```

And receive back:

```
Best tools for 'fetch a specific URL' (ranked by relevance):
1. open_url (score=0.4217) — Fetch a URL and return a clean text excerpt.
   ↳ when to use: Use this when you need exact content from a specific URL. Prefer this after search results identify a likely source.
2. playwright_browser (score=0.3104) — Drive a headless browser for JS-rendered or interactive pages.
   ↳ when to use: Use for pages requiring interaction or anti-bot protection.
3. web_search (score=0.1875) — Search the web with a configurable provider.
   ↳ when to use: Use when you need fresh information from the internet.
```

Directly exposed tools such as `open_url` are called normally. For a hidden
connector or MCP tool, discovery and execution look like:

```json
{"name":"tool_search","arguments":{"query":"query production logs","limit":3,"detail":"schema"}}
{"name":"call_tool","arguments":{"name":"observability__query_logs","arguments":{"query":"service:api level:error"}}}
```

`call_tool` is not a security bypass. The delegated tool is checked again
under its own contract and identity before it runs.

## Configuration

```python
ToolSearchTool(
    max_limit=10,        # hard cap on results — prevents prompt bloat
    default_limit=5,     # default when `limit` not passed
    token_bonus=0.12,    # weight for exact-token hits in scoring
)
```

Override at agent construction:

```python
from shipit_agent.tools import ToolSearchTool

agent = Agent.with_builtins(
    llm=llm,
    # You can't pass ToolSearchTool to with_builtins directly, but you can
    # replace it afterward:
)
agent.tools = [t for t in agent.tools if t.name != "tool_search"]
agent.tools.append(ToolSearchTool(max_limit=15, default_limit=8, token_bonus=0.20))
```

## Output format

The tool output includes:

- **`text`** — ranked markdown list for the LLM to read
- **`metadata.query`** — the original query
- **`metadata.limit`** — the effective limit after clamping
- **`metadata.total_candidates`** — total number of tools considered
- **`metadata.detail`** — effective detail level: `name`, `description`, or `schema`
- **`metadata.matches`** — structured ranked matches, including schemas when requested
- **`metadata.discovered`** — MCP tools added to the host-side catalog by this search
- **`metadata.discovery_failures`** — server discovery failures without suppressing local matches

## Where tool info comes from

`ToolSearchTool` reads from `context.state["available_tools"]`, which the runtime populates in `runtime.py` with every registered tool's:

- `name`
- `description`
- `prompt_instructions`
- `schema` (kept host-side until `detail="schema"` is requested)

This means MCP tools, connector tools, and custom tools are all searchable as long as they set those three fields on their schema.

## When to use it

| Scenario | Use `tool_search`? |
|---|---|
| Agent has 5 tools, all obviously different | ❌ Overkill |
| Agent has 15+ tools with overlapping capabilities | ✅ Highly recommended |
| Many MCP tools attached with similar names | ✅ Essential |
| Research agent that needs to reason about capability choice | ✅ Great fit |
| Simple chatbot with no tool loop | ❌ No tools to search |

## Prompt pattern

For lazy models like `gpt-4o-mini`, explicitly instruct the agent to use `tool_search` first:

```python
prompt = (
    "Before calling any other tool, first call `tool_search` to confirm "
    "which tool fits. Then proceed with the task.\n\n"
    "Task: ..."
)
```

## Related

- [Prebuilt tools](prebuilt-tools.md) — full list of built-in tools
- [Custom tools](custom-tools.md) — add your own discoverable tools
