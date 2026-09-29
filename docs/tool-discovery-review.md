# Tool discovery review

## Implemented

The ordinary Agent defaults to `deferred_tools="auto"`. Catalogs above ten
tools or the schema budget expose up to nine working tools and one discovery tool. Existing ToolSearchTool
instances are reused, including custom names. A user tool named search_tools
is preserved and the runtime discovery tool receives a collision-free name.
Explicit False, True, named deferral, and code mode remain supported.

Core selection uses caller priority, bounded session reuse, existing core capabilities and registration
order. Search uses weighted lexical matches over tool metadata. Exact names
load only that tool. CamelCase and Unicode words are supported. A search miss
does not activate unrelated tools. Tool execution still traverses permissions.

Discovered schemas append after previously advertised schemas in the run.
This preserves ordering; it does not guarantee provider prompt-cache hits.
Search results are bounded previews with full schemas supplied next step.

## Validation

Focused runtime, streaming, async, provider contract, MCP, permission, history
and context tests: 226 passed, one skipped on the development environment.
These are deterministic tests, not live provider quality evaluations.

Reproduce the payload benchmark:

```sh
PYTHONPATH=. .venv/bin/python scripts/benchmark_tool_discovery.py
```

The benchmark runs twenty successful fixture tool operations and counts
serialized messages, system prompts and schemas on every request. Discovery
adds one request for catalogs above ten tools.

| Catalog | Eager request characters | Auto request characters | Reduction |
| --- | ---: | ---: | ---: |
| 10 | 465,426 | 465,426 | 0% |
| 30 | 862,536 | 557,032 | 35.4% |
| 100 | 2,251,728 | 557,053 | 75.3% |

These synthetic payload measurements do not measure billable tokens, cache
discounts, real LLM tool selection accuracy, or twenty user conversation turns.

## Additional implementation and live evaluation (2026-09-27)

Repository regression suite: 4,153 passed, 31 skipped (excluding manual live
harnesses and the notebook test), with one existing collection warning.

- `DiscoveryPolicy`: initial tool count and approximate schema-token budget.
  Defaults are ten tools, 4,096 estimated schema tokens, three reusable tools.
  Discovery itself is retained even if the budget is smaller than its schema.
- Schema-fingerprinted, bounded session reuse and durable session checkpoints;
  permissions are re-evaluated, and conditional approval still happens at call time.
- `AgentChatSession` retains runtime state between sends without sharing it
  with other chat sessions.
- Dictionary histories retain native tool calls and result IDs.
- OpenAI/LiteLLM/Anthropic finish reasons are surfaced; run summaries expose
  incomplete output, failed tool results and recovery events.
- OpenAI/LiteLLM inclusive prompt-token accounting no longer double-counts cache
  reads in calibration, run-summary cost estimates or cost hooks.
- `ToolOutput.from_records` supplies explicit paged field projections while
  preserving canonical JSON. It does not select relevance or redact secrets.
- Failed nested code-mode tools raise across the bridge in sync and async paths.

Two actual Gemma 31B / Bedrock sessions used `Agent.stream()`, each with 20
user messages: five case lookups, five immediate recalls, five calculations,
and five first-versus-latest cross-turn recalls. The catalog comprised twenty
local fixture utilities plus an in-process MCP case archive. Evidence was
synthetic and verifiable; no production cases were accessed.

| Policy | Input tokens | Output tokens | Exact evidence checks |
| --- | ---: | ---: | ---: |
| All schemas visible | 103,216 | 652 | 20/20 |
| Auto discovery + session reuse | 82,613 | 673 | 20/20 |

Observed input reduction: approximately 20%. These are single-session samples,
not a statistical guarantee or a comparison against old production failures.
Reported cache reads were 4,176 and 512 respectively (subsets of input, not
extra input). One auto-session lookup took 50.2 seconds; provider latency is
not uniformly low. Neither session reached compaction. This does not validate
production MCP transports, all providers live, or context-limit memory recall.

Reproduce (billed calls; credentials are read locally and never printed):

```sh
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py --live --provider bedrock --model google.gemma-4-31b --turns 20
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py --live --provider bedrock --model google.gemma-4-31b --turns 20 --eager
```

## Remaining improvements and tradeoffs

1. **Exact schema accounting.** The initial budget is portable and approximate.
   Provider-specific tokenizers can improve accuracy; runtime request fitting
   remains the final protection against context overflow.
2. **Catalog indexing and semantic retrieval.** Current search is local lexical
   ranking, not semantic understanding. Benchmark paraphrases and ambiguous
   tools before introducing an embedding dependency. Cache indexes by catalog
   fingerprint and tenant, never share authorized catalogs across users.
3. **Durable discovery reuse.** Session stores now persist versioned schema
   fingerprints. Hosts owning history can hand off the run summary's
   `tool_discovery` through Agent metadata; the runtime checks session identity,
   current schemas and permissions. Hosts must authorize the session store.
   This is not a shared cross-tenant catalog cache.
4. **Tool-result projections.** Prefer meaningful model_text summaries, filters,
   pagination and recall handles over returning complete large datasets.
   Authorship comparisons and forensic analysis must retain exact source text.
5. **Provider cache measurement.** Compare uncached input, cache reads, output,
   latency and task success on real multi-turn workloads. Schema ordering alone
   cannot reproduce a provider's native deferred-loading cache protocol.

The initial ten-tool budget is not a permanent maximum: tools discovered during
a run stay available. Applications explicitly passing deferred_tools=False will
need to opt into auto. This change does not modify DRK's own upstream tool
routing; a tool removed before registry construction is not searchable.

## Integration and compaction stress testing

- DRK now enables auto discovery with the compatible SDK and hands off a
  checkpoint from its active message branch. Its own history remains authoritative.
  Older SDK deployments retain eager behavior until upgraded. Four targeted DRK
  tests passed, including real runtime streaming with fixture tools.
- Tool guidance distinguishes answering from existing evidence, executing a
  loaded capability, and discovering a missing capability. MCP availability
  alone is not a reason to call a tool or check a connection.
- Agent cloning/chat reconstruction no longer reactivates inherited plugins or
  duplicates their tools/hooks. Callback lists are isolated on cloning. Explicit
  plugin overrides still activate their contributions onto the supplied config;
  create a fresh Agent to remove previously activated contributions.
- Model-aware schema counting uses the existing cached tokenizer with an
  approximate fallback, not an exact count for every provider.
- The regression suite passed 4,162 tests with 31 skips and one collection
  warning. A real stdio fixture additionally passed discovery, execution and
  reconnect testing. No production MCP data was used.

Two Gemma 31B stress runs each completed 20 user messages with a deliberately
small 4,200-token context budget and a real stdio MCP subprocess. Both triggered
one compaction and passed 18/20 exact evidence checks. They consumed 72,400 /
72,794 input tokens and 727 / 688 output tokens respectively. Both failed two
late first-versus-latest entity recalls; a chronology-focused summary prompt
alone did not resolve them. Do not treat these runs as proof of lossless memory.
Production-sized contexts and other live providers still need separate coverage.

A third traced stress run reproduced 18/20. Its actual handoff contained an
answer to the old last question instead of a summary. Inspection found that
OpenAI-compatible and LiteLLM adapters dropped the separate `system_prompt`
argument used by compaction. Both now prepend it when the messages do not
already contain a system message; regression tests check no duplication or
mutation. Compacted handoffs are also excluded from human-turn numbering.
Another live sample refused discovery from the outset (0/20, no compaction,
55,420 input / 385 output tokens). This is a real failure, not a passing sample.
Tool reminders now explicitly permit reuse of verified conversation evidence,
and depth guidance no longer contradicts serial-only tool calling.

Final run with these fixes: **20/20 exact evidence checks**, one completed
compaction, real stdio discovery/calls, 76,964 input / 1,188 output tokens
(256 cache-read tokens included in input). The traced handoff now contains the
requested structured summary and explicit case/value associations. Six calls
were executed: one discovery and five lookups; follow-up answers reused history.
This is one successful final sample, not statistical proof that the earlier
discovery refusal cannot recur. Final regression: **4,168 passed, 31 skipped**,
one existing collection warning; targeted DRK integration: **4 passed**.

To retain reproducible metrics (new files only) and optionally inspect synthetic
request histories:

```sh
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py --live --provider bedrock --model google.gemma-4-31b --turns 20 --context-window 4200 --mcp-stdio --trace-fixture-requests --report /tmp/shipit-eval-new.jsonl
```

## Primary references

- [OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search):
  deferred schema loading and discovery cost/latency tradeoffs.
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching):
  reuse depends on stable prefixes, including tool definitions and ordering.
- [Anthropic advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use):
  tool search and selectively loading definitions.
- [Anthropic code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp):
  filter tool data before sending it into model context.

These sources support design principles; they do not establish that Codex or
Claude Code use this project's exact nine-plus-one policy.
