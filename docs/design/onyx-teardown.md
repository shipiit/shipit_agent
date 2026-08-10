# How Onyx runs an agent — and what shipit-agent should take from it

A teardown of `onyx-dot-app/onyx` (`/tmp/onyx`, `backend/onyx/`), written against
a concrete failure in our own runtime: one drk_cache turn billed **31,784 prompt
tokens on iteration 3**, with `cache_read_input_tokens: 0`.

Every claim below carries a `file:line` from the Onyx tree. Where I am
extrapolating rather than reporting, the line says **[inference]**.

---

## 0. The number we are trying to explain

From the live capture (`agent_live_test.txt`):

```
agent_decision   Searching echo.
  -> CALL search_echo {}                    ← empty arguments
agent_observation Searched echo.
  -> CALL get_echo {'key': 'ee068c7e-…'}
ANSWER: I have searched the Echo intelligence feed for "Qilin."
```

`search_echo({})` returned **13,534 characters ≈ 3,400 tokens** — 15 entries, of
which one was Qilin, one of them raw `<p><a class="mention_user" …>` markup.
That result sits in the message list from iteration 2 onward, so it is sent on
iteration 2 **and** iteration 3: **~6,800 tokens for a search that never
filtered anything.**

Nothing in Onyx would have prevented the empty argument. What Onyx does have is
a discipline for making sure that when a model does something wasteful, you do
not pay for it on every subsequent inference.

---

## 1. The single most important thing in the repo

Onyx ships a design document — `backend/onyx/chat/README.md` — that records an
experimental result most agent frameworks never measure:

> *"if there is a line of instructions effectively saying 'If you try to use some
> tools and find that you need more information or need to call additional
> tools, you are encouraged to do this', having this in the Tool section of the
> System prompt makes all the LLMs follow it well but if it's even just a
> paragraph away like near the beginning of the prompt, it is often ignored.
> The difference is as drastic as a **30% follow rate to a 90% follow rate** by
> even just moving the same statement a few sentences."*
> — `chat/README.md`

Read that against our live failure. Our depth instruction exists — I wrote it
into `shipit_agent/prompts/default_agent_prompt.py:21-25`:

```
- **A search is the beginning of the work, not the end of it.** When a search
  returns several relevant items and the question asked for detail, depth or
  "more", open the most relevant ones …
```

It is item 6 of 11 in a flat `Tool behavior:` bullet list, with no heading, no
tool name attached, and no proximity to the tool it governs. The model ignored
it. Onyx's finding predicts exactly that.

**This is the highest-leverage change available to us, and it costs nothing.**

---

## 2. How Onyx structures the tool section

Not one flat list. A header plus one `##` section per tool, and — critically —
**only for tools actually available this cycle**.

- `prompts/tool_prompts.py:3` — `TOOL_SECTION_HEADER = "\n# Tools\n\n"`
- `prompts/tool_prompts.py:23` — `INTERNAL_SEARCH_GUIDANCE`, opens with `## internal_search`
- `prompts/tool_prompts.py:34` — `WEB_SEARCH_GUIDANCE` → `## web_search`
- `prompts/tool_prompts.py:47` — `OPEN_URLS_GUIDANCE` → `## open_url`
- `prompts/tool_prompts.py:55` — `PYTHON_TOOL_GUIDANCE` → `## run_python`

Assembled in `chat/prompt_utils.py` and gated on availability. The reason for
gating is in the code, not a guess — `chat/llm_loop.py:682-685`:

> *"The open_url nudge is gated on the tool actually being available; otherwise
> the model is told to call a tool it doesn't have and leaks confusing
> 'open_url is not available' replies."*

Two Onyx guidance blocks are worth quoting because they are Onyx solving
problems we independently diagnosed:

**On depth after search** — `prompts/tool_prompts.py:47`:
> *"You should almost always use open_url after a web_search call."*

Not "consider opening results." *Almost always.* That is a far stronger
instruction than ours, attached directly to the tool it governs.

**On batching** — `prompts/tool_prompts.py:55`:
> *"batch multi-step work into a single script per call: e.g. load a workbook
> once, read all needed sheets, apply all edits, and save the result in one
> execution — **not one small step per call**."*

Same problem as our one-call-per-turn burn, solved in the tool's own section.

**On repetition** — `prompts/tool_prompts.py:7`:
> *"Do not repeat the same or very similar queries if it already has been run in
> the chat history."*

We enforce this mechanically in `runtime_core.py` with a SHA-256 memo. Onyx
states it in prose *and* keeps the arguments visible in history so the model can
see what it already ran (§4). Both layers are worth having.

---

## 3. Reminders: the mechanism we have no equivalent for

Onyx appends a short instruction block **at the very end of the context**, after
everything else, as a `USER_REMINDER` message.

- `chat/prompt_utils.py:127` — `build_reminder_message(...)`
- `chat/llm_loop.py:671` — `select_reminder_text(...)`
- `chat/llm_loop.py:960` — built fresh **every cycle** and passed into history
  construction

The rationale, from `chat/README.md`:

> *"Reminder messages are placed at the end of the prompt because all model fine
> tuning approaches cause the LLMs to attend very strongly to the tokens at the
> very back of the context closest to generation. This is the only way to get the
> LLMs to not miss critical information and for the product to be reliable."*

And on discipline:

> *"It is less detailed than the system prompt and should be very targetted for
> it to work reliably and also not interfere with the last user message."*

Note what `select_reminder_text` actually does — it is *state-dependent*
(`chat/llm_loop.py:671-695`). After a web search, with `open_url` available and
cycles remaining, the reminder becomes `OPEN_URL_REMINDER`. That is a
dynamically-injected "go deeper" nudge fired at exactly the moment our agent
stops and answers from one result.

**This is the direct structural fix for the `search_echo` → answer-from-one-hit
failure.** We have nothing like it.

---

## 4. Tool results are evicted from history

`chat/chat_utils.py:645`:

```python
def _build_tool_call_response_history_message(
    tool_name, generated_images, tool_call_response
) -> str:
    if tool_name != IMAGE_GENERATION_TOOL_NAME:
        return TOOL_CALL_RESPONSE_CROSS_MESSAGE
```

And the constant, `prompts/chat_prompts.py:95`:

```python
TOOL_CALL_RESPONSE_CROSS_MESSAGE = """
This tool call completed but the results are no longer accessible.
""".strip()
```

Every prior-turn tool result — a 13,534-character search dump included —
collapses to nine words. The rationale, from `chat/README.md`:

> *"Tool Call details like the search query and other arguments are kept in the
> history as this is information rich and generally very few tokens."*

**The arguments survive; the payload does not.** The model retains what it
searched for and loses what came back — which is the correct trade, because
anything that mattered is already in its own written answer.

**Scope, stated honestly:** the constant is named `CROSS_MESSAGE` and is applied
in `convert_chat_history` (`chat/chat_utils.py:679`), which builds history from
*prior turns*. This is a multi-turn win. It would **not**, on its own, have
fixed the 31,784 number, which was iteration 3 of a single turn. See §5 for what
does.

---

## 5. What Onyx does *within* a turn — the part that matters most

This is the mechanism I expected not to find, and it is there.

`chat/llm_loop.py:828` opens the cycle loop:

```python
for llm_cycle_count in range(MAX_LLM_CYCLES):
```

Tool responses are appended to `simple_chat_history` at `chat/llm_loop.py:1288`,
so the list grows within the turn exactly as ours does. But at
`chat/llm_loop.py:971` — **inside the loop, every single cycle** — Onyx rebuilds
the history under a hard token budget:

```python
tool_token_budget = compute_all_tool_tokens(final_tools, token_counter)
truncated_message_history = construct_message_history(
    system_prompt=system_prompt,
    simple_chat_history=simple_chat_history,
    reminder_message=reminder_msg,
    available_tokens=max(0, available_tokens - tool_token_budget),
    …
)
```

Three things to take from those six lines:

1. **The budget is re-applied on every iteration**, not once at turn start. Our
   runtime caps each tool output individually (`max_tool_output_chars=16_000`)
   but never asks "what does the whole prompt weigh right now?"

2. **Tool schemas are counted against the budget** —
   `compute_all_tool_tokens` (`tools/utils.py:33`) sums
   `token_counter(json.dumps(tool_definition))` per tool
   (`tools/utils.py:39-45`). Onyx knows that 68 tool schemas re-sent every cycle
   is a real cost and subtracts it. We do not measure this at all.

3. **Truncation is oldest-first with an audit trail.**
   `construct_message_history` (`chat/llm_loop.py:368`) keeps the last user
   message and everything after it as non-negotiable
   (`chat/llm_loop.py:454-462`), then fills backwards from the budget
   (`chat/llm_loop.py:471-483`). Dropped files are not silently lost — their IDs
   are collected (`chat/llm_loop.py:489-503`) and a "forgotten files" metadata
   message is injected so the model knows they existed and can re-read them
   (`chat/llm_loop.py:509-521`).

There is also a correctness detail worth stealing outright —
`chat/llm_loop.py:574`, `_drop_orphaned_tool_call_responses`:

> *"leaves a later TOOL_CALL_RESPONSE message in context. Some providers (e.g.
> Ollama) …"*

Truncating history can strip an assistant tool-call message while leaving its
orphaned response behind, which some providers reject outright. Any truncation
we add needs the same guard.

---

## 6. Cycle control: the last cycle cannot call a tool

`chat/llm_loop.py:830`:

```python
out_of_cycles = llm_cycle_count == MAX_LLM_CYCLES - 1
…
elif out_of_cycles or ran_image_gen:
    # Last cycle, no tools allowed, just answer!
    tool_choice = ToolChoiceOptions.NONE
```

`MAX_LLM_CYCLES` defaults to **6** (`configs/chat_configs.py:14`). On the final
cycle tools are removed from the request entirely — which both guarantees an
answer and drops the entire tool-schema block from the most expensive prompt of
the turn. Onyx also supports the inverse, `ToolChoiceOptions.REQUIRED` pinned to
a single tool (`chat/llm_loop.py:832-837`).

Parallel tool calls are first-class: `run_tool_calls` takes the whole list and a
`max_concurrent_tools` (`chat/llm_loop.py:1060-1074`), and the UI is told to
branch when there is more than one (`chat/llm_loop.py:1044`).

---

## 7. MCP handling

`tools/tool_implementations/mcp/mcp_tool.py:56`:

```python
def _normalize_parameters_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    # Azure OpenAI rejects object schemas that omit `properties` with
    # "object schema missing properties". MCP servers (e.g. AWS Knowledge MCP's
    # aws___list_regions) may legally return `{"type": "object"}` with no
    # properties for zero-arg tools, so seed `properties: {}` ourselves.
```

**Correcting an earlier claim of mine:** I previously suggested this was
relevant to the `search_echo({})` bug. Having now read it — it is not. It seeds
`properties: {}` so Azure and Bedrock accept the schema. It does **not** add
`required`, does not constrain arguments, and would not have prevented an empty
call. It is a compatibility shim worth adopting for provider robustness, and
nothing more.

Two naming mechanisms that are genuinely better than ours:

- **Collision-only disambiguation** — `tools/tool_constructor.py:55`:
  ```python
  def _disambiguate_mcp_tool_names(tools: list[Tool]) -> None:
      tool_name_counts = Counter(tool.name for tool in tools)
      for tool in tools:
          if isinstance(tool, MCPTool) and tool_name_counts[tool.name] > 1:
              tool.use_disambiguated_name()
  ```
  Short names stay short; only actual collisions get the
  `mcp_{server}_{tool}` prefix (`mcp_tool.py:101`). Our
  `include_server_in_tool_names` is all-or-nothing, which pays the prefix cost on
  every tool name in every schema on every cycle.

- **Name sanitisation** — `tools/tool_name.py`, because *"Bedrock rejects
  toolUse.name values that don't match `[a-zA-Z0-9_-]+`, and OpenAI imposes the
  same constraint."* We are on Bedrock. Worth having.

---

## 8. Ranked recommendations

Ordered by evidence and cost, not novelty.

### 1. Restructure the tool prompt into per-tool sections — *free, highest confidence*
Replace the flat `Tool behavior:` list in `default_agent_prompt.py` with
`# Tools` plus one `## <tool_name>` section per **available** tool, and move the
depth instruction into the section for the search tool it governs. Onyx measured
30% → 90% on exactly this change. Our live run is a data point on the 30% side.

### 2. Add end-of-context reminders — *small, directly targets the observed failure*
A short, state-dependent block appended last, rebuilt each iteration. After a
search returns N results with detail requested and cycles remaining: *"You have
seen N results and opened 1. Open the most relevant remaining ones before
answering."* This is `select_reminder_text` applied to our failure mode.

### 3. Add `"required": ["query"]` to `search_echo` and `rl_groups` — *one line, largest single token saving*
Unchanged from my earlier analysis and unaffected by anything in Onyx. This is
the ~6,800 tokens. It is in drk_cache, not in shipit-agent.

### 4. Budget the whole prompt per iteration, not each output — *the real §5 lesson*
Add a `max_context_tokens` to `Agent`, measure tool-schema cost like
`compute_all_tool_tokens`, and truncate oldest-first before each call — with
`_drop_orphaned_tool_call_responses`-style guarding and a "what was dropped"
note. This generalises `max_tool_output_chars` from a per-result cap to a
whole-prompt ceiling.

### 5. Evict prior-turn tool payloads, keep the arguments — *multi-turn win*
Adopt `TOOL_CALL_RESPONSE_CROSS_MESSAGE`. Does not touch the 31,784 number;
matters as soon as a conversation runs past one turn.

### 6. No tools on the final iteration — *few lines*
Guarantees an answer and drops the schema block from the priciest prompt.

### 7. Collision-only MCP name disambiguation + name sanitisation — *cheap correctness*
`tool_constructor.py:55` and `tool_name.py`.

### 8. Adopt `_normalize_parameters_schema` — *provider robustness only*
Not a token fix. Not a correctness fix for empty arguments. Worth doing anyway.

---

## 9. What Onyx does not fix

- **The empty argument.** Gemma emitted a structurally valid `search_echo({})`.
  Healing never runs on a valid call, and no Onyx mechanism rejects one. Only a
  `required` list on the tool schema does.
- **`cache_read_input_tokens: 0`.** Onyx has no answer for a provider that gives
  no prompt-cache discount. On Gemma via bedrock-mantle we re-pay ~16.7k of
  system prompt plus schemas every cycle. A Claude model on the same Bedrock
  account would bill that prefix at roughly a tenth. **[inference — not measured
  on this stack]**
- **HTML in tool payloads.** One echo entry was almost entirely markup. That is
  a drk_cache serialisation issue.

---

## 10. The tool execution layer, in depth

Everything above concerned *what the model is told*. This section is *what
happens when it calls something* — `tools/tool_runner.py`, `tools/interface.py`,
`tools/models.py`.

### 10.1 Redundant parallel calls are merged, not executed

`tools/tool_runner.py:56`:

```python
MERGEABLE_TOOL_FIELDS: dict[str, str] = {
    SearchTool.NAME:    QUERIES_FIELD,   # "queries"
    WebSearchTool.NAME: QUERIES_FIELD,
    OpenURLTool.NAME:   URLS_FIELD,      # "urls"
}
```

`_merge_tool_calls` (`tools/tool_runner.py:63`) groups the model's calls by tool
name, and when a mergeable tool was called more than once in one response, it
concatenates the list-valued field and issues **one** call
(`tools/tool_runner.py:84-108`).

This is the counterpart to telling the model to batch. We push batching onto the
model via prompt (`default_agent_prompt.py:15-19`) and hope; Onyx *also* repairs
it mechanically on the way out. Three `web_search` calls become one call with
three queries — one round trip, one result block in history instead of three.

Note the design requirement this implies: the tool's schema must take a **list**
(`queries`, `urls`), not a scalar.

**[inference — my design proposal, not an Onyx pattern]** The same shape applied
to drk_cache would matter: a `get_echo` accepting `keys: list[str]` turns "open
three echoes" into one call and one result block. Of everything in this document,
this is the change most likely to cut the 31,784 number further once
`required: ["query"]` is in place.

### 10.2 A tool call never raises into the loop

`_safe_run_single_tool` (`tools/tool_runner.py:116`) catches three tiers and
converts every one into a normal `ToolResponse`
(`tools/tool_runner.py:147`, `:171`, `:198`):

```python
except ToolCallException as e:
    tool_response = ToolResponse(
        rich_response=None,
        llm_facing_response=GENERIC_TOOL_ERROR_MESSAGE.format(
            error=e.llm_facing_message),
    )
```

The two-audience error contract is explicit in `tools/models.py:31`:

```python
class ToolCallException(Exception):
    def __init__(self, message: str, llm_facing_message: str):
        # This is the full error message which is used for tracing
        super().__init__(message)
        # LLM made tool calls are acceptable and not flow terminating, this is
        # the message which will populate the tool response.
        self.llm_facing_message = llm_facing_message
```

**One error, two renderings** — a full trace with stack, args and tool_call_id
for the operator (`tools/tool_runner.py:157-169`), and a short actionable
sentence for the model. `ToolExecutionException` adds `emit_error_packet` to
control whether the *user* sees it too (`tools/models.py:42`).

There is also a hard ceiling: `TOOL_EXECUTION_TIMEOUT_SECONDS = 10 * 60`
(`tools/tool_runner.py:53`), and `SectionEnd` is emitted on **success or
failure** (`tools/tool_runner.py:220`) so the UI never hangs on a dead tool.

### 10.3 A failed call is retried by the loop, not abandoned

`chat/llm_loop.py:1079`:

```python
if tool_calls and not tool_responses:
    failure_messages = create_tool_call_failure_messages(tool_calls, token_counter)
    simple_chat_history.extend(failure_messages)
    continue
```

`create_tool_call_failure_messages` (`chat/chat_utils.py:925`) synthesises a
*well-formed pair* — the assistant tool-call message plus one
`TOOL_CALL_RESPONSE` per call (`chat/chat_utils.py:971-976`) — carrying
`TOOL_CALL_FAILURE_PROMPT` (`prompts/tool_prompts.py:82`):

> *"LLM attempted to call a tool but failed. Most likely the tool name or
> arguments were misspelled."*

The pairing matters as much as the message: an assistant tool-call without its
matching response is a malformed conversation that some providers reject
outright — the same invariant `_drop_orphaned_tool_call_responses`
(`chat/llm_loop.py:574`) protects on the truncation side.

This is a different philosophy from our `tool_healing.py`. We repair the *call*
by parsing prose into structure. Onyx repairs the *conversation* by telling the
model it failed and letting it try again. **They compose** — healing rescues a
call that was merely mis-formatted; the failure pair handles everything healing
correctly refuses (including the mangled `{"))Query:Qilin": "qilin"}` arguments
our `_plausible_argument_names` guard now rejects).

### 10.4 `override_kwargs` — arguments the model does not supply

From `tools/interface.py:75`:

```python
def run(
    self,
    placement: Placement,
    # Specific tool override arguments that are not provided by the LLM
    # For example when calling the internal search tool, the original user
    # query is passed along too (but not by the LLM)
    override_kwargs: TOverride,
    **llm_kwargs: Any,
) -> ToolResponse:
```

`Tool` is generic in the override type (`Tool(abc.ABC, Generic[TOverride])`,
`tools/interface.py:14`), so each tool declares its own — `SearchToolOverrideKwargs`,
`OpenURLToolOverrideKwargs`, `PythonToolOverrideKwargs`
(`tools/tool_runner.py:20-27`).

**This is a clean answer to a problem we have.** The original user query reaches
the search tool without the model having to retype it into the arguments.

**[inference]** Had `search_echo` been built this way, an empty `{}` from the
model would still have carried the user's question server-side. Onyx does not
make this claim; it follows from the mechanism. It would not fix the model's
behaviour, only make the tool robust to it.

There is a related honesty note in `chat/README.md`:

> *"in the Internal Search flow with query expansion, the Tool Call which was
> actually run differs from what the LLM provided as arguments. What the LLM
> sees in the history (to be most informative for future calls) is the full set
> of expanded queries."*

The model is shown what *actually ran*, not what it asked for — so its next call
is informed by reality.

---

## 11. The MCP connection layer, in depth

`server/features/mcp/` — `client.py` (341), `models.py` (676), `oauth.py` (718),
`ssrf.py` (67), `api.py` (2740).

### 11.1 Transport

`server/features/mcp/client.py:139` selects `streamablehttp_client` or
`sse_client` from a stored `MCPTransport` enum, with a per-call read timeout
(`client.py:165`):

```python
read_timeout_seconds=timedelta(seconds=MCP_TOOL_CALL_TIMEOUT_SECONDS)
```

Sessions are per-call: `call_tool` runs `session.initialize()` then
`session.call_tool(...)` (`client.py:247-251`). No long-lived session is held
across the agent loop.

### 11.2 Result flattening

`server/features/mcp/client.py:223`:

```python
def process_mcp_result(call_tool_result: CallToolResult) -> str:
    """Flatten MCP CallToolResult->text (prefers text content blocks)."""
```

It walks content blocks, taking `TEXT`, the `.text` of a `TextResourceContents`
`RESOURCE`, and for `RESOURCE_LINK` a one-line
`f"link: {uri} title: {title} description: {description}"`
(`client.py:226-241`), joining with `\n\n` and falling back to
`str(structuredContent)`.

Two things to take: **a resource link becomes one line, not an embedded payload**
— the model gets a pointer and can fetch it if needed. And the `# TODO: use
structured_content if available` at `client.py:225` marks the same opportunity
we have: structured content is far cheaper than prose text, and neither codebase
exploits it yet.

### 11.3 Credentials, headers, and auth failures

`tools/tool_implementations/mcp/mcp_tool.py:154` filters headers against
`DENYLISTED_MCP_HEADERS` (`server/features/mcp/models.py:62` — currently
`{"host"}`) and **logs which were dropped** rather than silently discarding them
(`mcp_tool.py:161-166`). `merge_mcp_headers` (`models.py:67`) merges
case-insensitively, later sources winning, and config validation rejects
duplicates and denylisted names outright (`models.py:147-151`).

The auth-failure message is the detail worth copying
(`mcp_tool.py:180-184`):

```python
auth_error_msg = (
    f"The {self._name} tool from {self.mcp_server.name} requires "
    "connection values. Tell the user to connect to the server "
    "from the MCP dropdown before using this tool."
)
```

It is not an error string. It is **an instruction to the model about what to
tell the user** — routed through the normal tool-response path as JSON, so the
turn continues and the user gets an actionable sentence instead of a stack
trace. Compare our behaviour when Langfuse OTLP returned 403 this session: the
agent stalled. Onyx's pattern is to make every failure a normal, informative
tool result.

`_AUTH_ERROR_INDICATORS` (`mcp_tool.py:36`) classifies errors by substring —
`"401"`, `"unauthorized"`, `"invalid api key"`, `"please reconnect to the
server"` — so an auth failure is distinguishable from a tool failure and can
prompt reconnection rather than a retry.

### 11.4 SSRF — the part most MCP integrations get wrong

`server/features/mcp/ssrf.py:1`:

> *"The MCP SDK builds its own URLs from server responses (WWW-Authenticate,
> OAuth metadata, redirects, dynamic client registration), so validating the
> stored `server_url` alone is insufficient. The guard is injected at the httpx
> transport so every request the SDK makes — each redirect hop, discovery,
> registration, and token request — is checked."*

`_SSRFGuardAsyncTransport` (`ssrf.py:40`) validates inside
`handle_async_request`, so with `follow_redirects=True` httpx re-enters per hop
and every redirect target is validated (`ssrf.py:41-43`). Levels are
admin-controlled; even at `DISABLED`, cloud-metadata and link-local stay blocked
(`ssrf.py:24-28`).

**If shipit-agent is ever pointed at a third-party MCP server, this is the
threat model.** A URL check at registration time is not sufficient — the SDK
fetches URLs the server chooses. This is a security gap in our MCP support, not
a token issue, and it is the one item in this document that is not about cost.

### 11.5 Tool definition shape

`mcp_tool.py:123` emits plain OpenAI function format:

```python
return {
    "type": "function",
    "function": {
        "name": self._name,
        "description": self._description,
        "parameters": _normalize_parameters_schema(self._tool_definition),
    },
}
```

The MCP `inputSchema` is passed through untouched apart from the
`properties: {}` seeding. **Onyx does not enrich, trim, or add `required` to
MCP-supplied schemas** — see the correction in §7. Schema quality is the MCP
server's responsibility, and for `search_echo` that server is ours.

---

## 12. Reasoning / thinking — how Onyx handles the model's own thought

This is the layer with the closest bearing on the bug I shipped and patched this
session (leaked call fragments reaching the UI, fixed with `_looks_like_prose`).
Onyx treats reasoning as a **first-class third channel**, alongside answer and
tool calls — not as text to be filtered.

### 12.1 Reasoning is a separate stream, not part of the answer

`chat/llm_step.py:1334`:

```python
if delta.reasoning_content:
    accumulated_reasoning += delta.reasoning_content
    state_container.set_reasoning_tokens(accumulated_reasoning)
    if not reasoning_start:
        emit(ReasoningStart())
    emit(ReasoningDelta(reasoning=delta.reasoning_content))
    reasoning_start = True
```

Three packet types — `ReasoningStart` / `ReasoningDelta` / `ReasoningDone`
(`chat/llm_step.py:54-56`) — mirror the answer packets, with
`_close_reasoning_if_active()` (`chat/llm_step.py:1190`) as the single place the
block is closed, called on every exit path (`:1240`, `:1359`, `:1405`).

Reasoning is persisted incrementally to the state container as it streams
(`:1338`), so a cancelled turn still saves partial thinking.

**Contrast with ours.** Our `agent_decision` / `agent_observation` narration is
derived from `response.content` after the fact and defended by heuristics
(`_looks_like_prose`, `_NOT_PROSE`). Onyx never needs the heuristic for
providers that expose `reasoning_content`, because thinking arrives on its own
channel and is never eligible to become the answer.

### 12.2 One narrow case where prose is reclassified as thinking

I initially read this as Onyx synthesising a reasoning channel for models that
lack one. Having read the actual guard, it is not that. `chat/llm_step.py:1223`:

```python
# When tool_choice is REQUIRED, content before tool calls is reasoning/thinking
# about which tool to call, not an actual answer to the user.
# Treat this content as reasoning instead of answer.
if is_deep_research and tool_choice == ToolChoiceOptions.REQUIRED:
    accumulated_reasoning += content_chunk
    …
    return
```

**Both conditions must hold.** `is_deep_research` defaults to `False`
(`chat/llm_step.py:1056`) and is not passed by `run_llm_loop` — it is threaded
only from `chat/llm_step.py:1553-1576`. So in the ordinary chat path this branch
never fires; everything falls through to *"Normal flow for AUTO or NONE tool
choice"* (`:1239`).

What it demonstrates is still worth having: when the runtime **knows by
construction** that prose cannot be an answer — a tool was mandatory, so text
arriving before it is deliberation — it reclassifies positionally rather than by
sniffing content.

That principle applies to us, but it is not a drop-in replacement for
`_looks_like_prose`. Our leak (image 102) happened in the ordinary path, where
Onyx has no equivalent guard either. The mechanism that actually protects Onyx's
stream in the normal case is §12.3, not this. **[inference]** — the positional
idea could be extended to our `tool_choice`-forced iterations, but Onyx does not
do so.

### 12.3 Leaked tool-call markup is stripped from the stream

The bug I hit — `Running rl groups off,name":"} // ERROR in thought process`
reaching the user — has a dedicated streaming state machine in Onyx
(`chat/llm_step.py:120-160`).

It scans for `<function_calls` with a **valid tag boundary follower**
(`_is_valid_function_calls_open_follower`, `:157` — only `>`, whitespace, or
end-of-text), tracks `_inside_function_calls_block`, and holds back a partial
suffix that might be the start of the marker split across chunks
(`_matching_open_marker_prefix_len`, `:145`). On `flush()` an unterminated block
is **dropped, not emitted** (`:133-139`).

That last detail is the one my fix lacks: a truncated `<function_calls` at
stream end is discarded rather than shown. Mine inspects the assembled string
after the fact and can only reject it wholesale.

### 12.4 Reasoning text is searched for tool calls

`chat/llm_loop.py:202`, `_try_fallback_tool_extraction` — Onyx's counterpart to
our `tool_healing.py`. Three trigger conditions (`:239-243`):

```python
should_try_fallback = (
    (tool_choice == ToolChoiceOptions.REQUIRED and no_tool_calls)
    or reasoning_but_no_answer_or_tools
    or xml_tool_call_text_detected
)
```

The middle one is the insight: **reasoning present, but no answer and no tool
calls** means the model almost certainly wrote its call into its thinking.
Extraction then tries `answer` → `raw_answer` → **`reasoning`**
(`:251-271`), and runs **at most once per step** (`fallback_extraction_attempted`,
`:225-226`) so a bad response cannot loop.

Our `heal_tool_calls` only ever scans the response content. If Gemma writes a
call into a reasoning channel, we miss it entirely.

### 12.5 Schema-aware matching — stronger than our name guard

`chat/llm_step.py:598`, `_try_match_json_to_tool` accepts four shapes. The first
three are the ones we handle. **Format 4** (`:640-653`) is the one we do not:

```python
for tool_name, func_def in tool_name_to_def.items():
    params = func_def.get("parameters", {})
    properties = params.get("properties", {})
    required = params.get("required", [])
    if not properties:
        continue
    # Check if all required parameters are present (empty required = all optional)
    if all(req in json_obj for req in required):
        matching_props = [prop for prop in properties if prop in json_obj]
        if matching_props:
```

A bare arguments object with no tool name is matched to a tool **by validating
its keys against that tool's declared schema** — all `required` present, at least
one `properties` key overlapping.

This is stronger than my `_plausible_argument_names` regex, which only asks
"does this key look like an identifier?". Against the real Gemma wreckage we saw
— `{"))Query:Qilin": "qilin"}` and `{":[{": ","}` — both approaches reject.

**[inference — worked through by me, not tested]** Schema matching should also
reject `{"quary": "Qilin"}`, a plausible-looking typo my regex promotes, and
should *recover* a bare `{"query": "Qilin"}` that mine cannot use at all because
no tool name is present. Both follow from the `required`/`properties` check at
`:650-653`; neither is a case Onyx documents.

There is also argument coercion worth taking: `_try_parse_json_string`
(`chat/llm_step.py:190`) turns `queries: '["q1","q2"]'` into a real list, and
`_parse_tool_args_to_dict` (`:217`) handles double-encoded JSON —
`'"{\\"queries\\":[...]}"'`. Both are documented as observed model behaviour, not
speculation.

### 12.6 Reasoning effort is a first-class, provider-mapped setting

`llm/models.py:28`:

```python
class ReasoningEffort(str, Enum):
    AUTO = "auto"; OFF = "off"; LOW = "low"
    MEDIUM = "medium"; HIGH = "high"; XHIGH = "xhigh"
```

with the provider mapping documented in the docstring — OpenAI passes
`reasoning_effort` through, Claude maps to `budget_tokens`, Gemini to
`thinking_budget` via litellm, and `XHIGH` clamps to the provider's maximum.
It is threaded from the API down to `run_llm_step`
(`chat/llm_loop.py:713` → `:1005`) and is user-pinnable per session
(`USER_SELECTABLE_REASONING_EFFORTS`, `llm/models.py:50`).

Reasoning also costs a **display** cycle, not a tool cycle:
`reasoning_cycles += 1` (`chat/llm_loop.py:1008`) only shifts `turn_index` for
the frontend (`:996`) — the `MAX_LLM_CYCLES` budget is untouched. Thinking never
eats a tool-call opportunity.

### 12.7 An empty step is detected and surfaced

`chat/llm_step.py:1036`:

```python
return bool(delta.content or delta.reasoning_content or delta.tool_calls)
```

If a stream produces none of the three, it is logged as empty (`:1301-1306`) and
`_build_empty_llm_response_error` (`chat/llm_loop.py:135`) surfaces it — checked
against reasoning too (`:167-170`). A model that returns nothing produces a
visible error rather than a silent empty answer.

---

## 13. Recommendations 9–20 (continuing the §8 list)

Items 9–14 come from §§10–11; items 15–20 from §12. All rank below §8's items
1–3, which remain the three to do first.

Appended to the ranked list in §8; all lower priority than items 1–3 there.

### 9. Merge redundant same-tool calls before execution — *mirrors `_merge_tool_calls`*
And, in drk_cache, give `get_echo` a `keys: list[str]` parameter so "open three
echoes" is one call. This is the schema shape that makes merging possible.

### 10. Split tool errors into operator and model messages — *`ToolCallException`*
A `llm_facing_message` alongside the full trace. Today a raw exception string
reaches the model, which is both leaky and unhelpful to it.

### 11. Synthesise a failure message pair on a failed call and continue
`create_tool_call_failure_messages` + `continue`. Complements `tool_healing.py`
rather than replacing it — it covers the calls healing correctly refuses.

### 12. Add an `override_kwargs` channel to `Tool.run`
Server-supplied arguments the model never sees. Makes a tool robust to an
under-specified call, and lets us show the model what *actually* ran.

### 13. Guard outbound MCP traffic at the transport — *security, not tokens*
Per-hop SSRF validation, not one check on the stored URL. See §11.4.

### 14. Denylist and log filtered MCP headers; classify auth errors
`DENYLISTED_MCP_HEADERS`, `merge_mcp_headers`, `_AUTH_ERROR_INDICATORS`, and an
auth failure phrased as an instruction to the model — so a 403 produces a
sentence, not a stall.

### 15. Consume the provider's reasoning channel directly — *§12.1, high value*
Where the provider exposes `reasoning_content`, feed `agent_decision` /
`agent_observation` from it instead of deriving narration from
`response.content`. This removes the need for `_looks_like_prose` on those
providers entirely — the heuristic becomes the fallback, not the mechanism.

### 16. Strip leaked tool-call markup during streaming, not after — *§12.3*
A boundary-aware state machine that holds back partial markers across chunks and
**drops an unterminated block at flush**. My current fix inspects assembled text
and can only reject wholesale; it cannot un-emit what already streamed.

### 17. Scan the reasoning channel in `heal_tool_calls` — *§12.4*
Add `reasoning` to the extraction sources, and add Onyx's trigger condition
"reasoning present, no answer, no tool calls" — a strong signal the call was
written into thinking. Cap at one attempt per step.

### 18. Match bare argument objects against tool schemas — *§12.5, replaces a weaker guard*
Adopt Format 4: validate candidate keys against each tool's `required` and
`properties`. Strictly stronger than `_plausible_argument_names`, and it
recovers nameless `{"query": "Qilin"}` objects we currently discard. Add
`_try_parse_json_string` / `_parse_tool_args_to_dict` coercion alongside it.

### 19. Expose a provider-mapped `reasoning_effort` — *§12.6*
An enum mapped per provider (`budget_tokens` for Claude, `thinking_budget` for
Gemini), and reasoning that costs a display cycle rather than a tool cycle.

### 20. Error on a fully empty step — *§12.7*
No content, no reasoning, no tool calls should raise a visible error, not an
empty answer.

---

## 14. Sources

All paths relative to `/tmp/onyx/backend/onyx/`.

| Topic | Location |
|---|---|
| Context-management design + experiments | `chat/README.md` |
| History compression / summarisation | `chat/COMPRESSION.md`, `chat/compression.py` |
| Cycle loop, budget, reminders | `chat/llm_loop.py:828`, `:971`, `:671` |
| History construction & truncation | `chat/llm_loop.py:368-600` |
| Tool-result eviction | `chat/chat_utils.py:645`, `prompts/chat_prompts.py:95` |
| Per-tool prompt sections | `prompts/tool_prompts.py` |
| Reminder assembly | `chat/prompt_utils.py:127` |
| Tool token accounting | `tools/utils.py:33-45` |
| Tool interface | `tools/interface.py` |
| MCP tool | `tools/tool_implementations/mcp/mcp_tool.py` |
| Name disambiguation / sanitisation | `tools/tool_constructor.py:55`, `tools/tool_name.py` |
| Cycle limit | `configs/chat_configs.py:14` |
| Parallel-call merging | `tools/tool_runner.py:56-108` |
| Tool error contract | `tools/models.py:31-48`, `tools/tool_runner.py:116-225` |
| Failed-call retry pair | `chat/chat_utils.py:925`, `chat/llm_loop.py:1079` |
| MCP transport & result flattening | `server/features/mcp/client.py:139`, `:223` |
| MCP auth, headers | `mcp_tool.py:36`, `:154`, `:180`; `server/features/mcp/models.py:62` |
| MCP SSRF guard | `server/features/mcp/ssrf.py` |
| Reasoning stream | `chat/llm_step.py:1190`, `:1220`, `:1334` |
| Streaming markup stripper | `chat/llm_step.py:120-176` |
| Fallback tool extraction | `chat/llm_loop.py:202`, `chat/llm_step.py:419`, `:598` |
| Argument coercion | `chat/llm_step.py:190`, `:217` |
| Reasoning effort | `llm/models.py:28-50` |
