# Runtime reliability hardening

## Provider usage and budgets

OpenAI-compatible, LiteLLM, and Anthropic adapters preserve missing input/output
token counters as unknown. An explicit zero is valid; a missing, negative,
boolean, or non-integer value is not treated as free work. A reported total alone
cannot determine the input/output split or cache semantics.

Configured task/session budgets use this distinction to stop subsequent model
requests when accounting is unavailable. These remain soft, between-step limits,
not a guarantee that an in-flight request cannot exceed the limit. Cache savings
must be measured from provider-reported counters; these changes do not establish
a live cost reduction.

## MCP replay safety

The resilience wrapper retries allowlisted protocol discovery/read requests.
It does not replay `tools/call` or unknown methods automatically. A timeout or
disconnected socket does not prove the server failed to perform an action.
Applications needing retries for writes should use server-supported idempotency
or reconcile execution status first. This transport policy does not itself stop
a model from requesting the action again in a later step.

## File session identity

New session files use SHA-256-derived filenames, avoiding separator, filename
length, and case-insensitive filesystem collisions. Existing files can still be
read after verifying their embedded session ID. Subsequent saves use the new
filename; listings deduplicate legacy/current copies. Old files are not deleted.

This prevents filename collisions, not unauthorized access: the host application
must still authenticate users, authorize session access, and provide process-safe
coordination for multiple workers. In-process session locks are not distributed
locks. Do not treat the file store as a multi-tenant security boundary.

## Async chat lifecycle and forks

`AgentChatSession.asend`, `astream`, and `astream_packets` share the same chat
state as synchronous sends. Event/packet callbacks remain synchronous and should
be short and non-blocking. When abandoning a stream, explicitly close it (for
example with `contextlib.aclosing`); merely breaking an async loop is not a
guarantee of immediate cleanup. Closing these wrappers now awaits nested runtime
cleanup and honors the configured runtime cancellation policy.
Worker exceptions propagate after buffered events are drained; they no longer
silently end an async stream as though it succeeded.

```python
from contextlib import aclosing

chat = agent.chat_session(session_id=authorized_session_id)
result = await chat.asend("Review the evidence")
async with aclosing(chat.astream_packets("Compare with the earlier result", transport="sse")) as packets:
    async for packet in packets:
        await send_to_client(packet)
```

The host must authenticate and authorize `authorized_session_id` before creating
the chat. A disconnected client should close the iterator. Do not convert an
exception from the stream into a completed assistant message.

`SessionManager` binds returned chats to its own store without changing the
supplied agent. Forks deep-copy messages and discard derived facts, compaction
summaries, and discovery checkpoints; these can otherwise reference messages
after a historical fork point. Custom metadata is copied independently.

Session token budgets still live in chat/agent runtime state and are not a
durable company billing ledger. Reconstructing the agent can reset that budget;
production cross-worker spending limits need durable accounting and coordination.

## Validation boundaries

### Targeted evidence recall and app-building tools

Historical `recall_tool_result` accepts `query` alongside `call_id`, `offset`,
and `limit`. It searches literal text case-insensitively (not model-generated
regex), returning exact source text around the first match at or after offset.
Use a small `limit` when only a fact or error is needed. No-match responses are
explicit; normal paging remains available. The source result is unchanged.

The regression fixture retrieves a relevant excerpt under 750 characters from
over 400,000 characters of historical output. This is returned-text reduction,
not a claim about real provider token billing or task success.

Core workspace path resolution rejects similarly named sibling directories and
symlink escapes. This is a file-tool boundary, not an OS sandbox for subprocesses.
Exact edits reject empty search text, including `replace_all` requests.

An app-building regression uses real file tools and Python subprocesses to write
a WSGI greeting application, observe a failing assertion, read/edit the source,
and verify the corrected response. It runs through both `Agent.run` and
`Agent.stream`; model choices are scripted. It does not install dependencies,
start a public server, or establish autonomous real-model coding quality.

Regression coverage includes missing usage, cache-only usage, sync/stream budget
enforcement, ambiguous MCP writes, and colliding session IDs. Existing suites
cover large-catalog discovery, HTTP failure isolation, stream events, routing,
and session behavior. Fixture tests do not establish live Gemma/Bedrock quality,
production connector reliability, or comparative savings against another agent.

The concurrent chat regression runs two isolated twenty-turn chats, alternating
async sends and streams, with forty unique local tool executions. It checks prior
user turns on every model call, exact terminal output, retained tool results, and
separate usage totals. Its model and usage counts are scripted fixtures, not a
live quality or cost benchmark.

### Offline discovery measurement

`PYTHONPATH=. .venv/bin/python scripts/benchmark_tool_discovery.py` exercised
twenty successful fixture lookups per configuration. Automatic discovery versus
eager loading reduced serialized request characters by 10.7% with 30 tools,
56.6% with 100 tools, and 89.1% with 500 tools. With 10 tools it retained eager
loading (no reduction). Discovery added one model request in each deferred case.
These measure existing discovery behavior, not savings introduced by this patch.
They are payload measurements, not tokenizer counts, cache hits, billed cost, or
real-model task-success measurements.
## MCP response and pagination boundaries

HTTP MCP responses must match the outgoing request ID and contain an object
result. Streamable HTTP skips unrelated SSE responses and accepts session
headers only after response validation. This prevents unrelated content from
being treated as tool evidence; it does not change SSE into incremental reading.

`RemoteMCPServer(..., max_discovery_pages=100)` bounds each paginated listing.
Increase the positive integer limit for servers with unusually small pages.
Cursors remain opaque and are forwarded unchanged, following the
[MCP pagination specification](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination).
Malformed pages, repeated cursors, and exhausted page budgets raise `MCPError`
inside discovery. Failed tool discovery does not publish a partial catalog.
The existing optional resources/prompts listing APIs still translate MCP errors
to empty lists; they do not yet distinguish unsupported methods from failures.

Regression coverage includes HTTP/SSE response identity, malformed payloads,
session-header validation, cursor preservation, and bounded discovery. These
are local transport fixtures, not live-provider or production-server validation.
