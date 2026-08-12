# OpenSRE Agent Runtime Audit

This audit compares SHIPIT with Tracer Cloud's OpenSRE at commit `fbec9fe`.
OpenSRE is an SRE application and framework, not a drop-in general-purpose
agent SDK, so the useful outcome is a set of runtime patterns rather than a
code transplant.

## Patterns worth transferring

| OpenSRE pattern | Why it works | SHIPIT status |
|---|---|---|
| `TurnSnapshot.available_tools` and `active_tools` | Keeps the complete host catalog separate from the small model-visible surface. | Already covered by automatic progressive context, `tool_search`, `call_tool`, and deferred MCP discovery. |
| Source circuit breaker | Stops paying repeated connection timeouts after a source is proven unreachable. | Added as a tool-scoped, turn-scoped transport circuit with sticky success and trace metadata. |
| Gather goal review | Prevents the model from ending after listing schemas without fetching requested evidence. | Added as a deterministic discovery-only completion guard, avoiding OpenSRE's extra reviewer LLM call. |
| Context budget ledger | Counts messages, system prompt, and tool schemas; evicts expensive exchanges first. | SHIPIT already performs model-aware compaction, prior-result eviction, per-result caps, parallel-group caps, and optional full-result spill. |
| Compact skill index | Loads detailed instructions only when a skill is relevant. | SHIPIT selects bounded relevant skills and injects only selected skill instructions/tools. Further index compaction remains useful for very large custom catalogs. |
| Write-ahead action recording | Supports recovery without blindly replaying mutations. | SHIPIT has persisted sessions/traces; durable mutation-intent recovery remains a future deep-agent feature. |

## Deliberate differences

SHIPIT does not add a second LLM goal reviewer after every tool run. That can
catch broad incomplete actions, but it increases latency and tokens and can
incorrectly force more work. The implemented guard uses structured tool-result
metadata and runs at most once, specifically for the observed failure mode:
capability discovery succeeded but no capability executed.

The transport breaker is also deliberately narrow. It opens only for endpoint
connectivity signatures and never for authentication, malformed input, empty
results, or a reachable vendor reporting that its downstream data source is
offline. This preserves argument repair while stopping wasteful retries that
cannot succeed during the turn.

## Remaining high-value work

1. Add a durable write-ahead log for mutating tool intent, approval, execution, and recovery.
2. Add a provider-reported token ledger that attributes prompt cost to system text, schemas, history, and tool results.
3. Add optional host-side semantic reranking for catalogs where lexical tool search is insufficient.
4. Add per-connector health state across runs with backoff, while keeping the current per-turn circuit as the immediate safety layer.
