# Progressive skills, discovery diagnostics and task budgets

Ordinary `Agent`, including `stream()` and async APIs, supports:

```python
agent = Agent(
    llm=llm,
    tools=authorized_tools,
    mcps=authorized_mcp_servers,
    skill_registry=registry,
    progressive_skills=True,
    max_task_tokens=50_000,
)
```

## Progressive skills

Opt-in preserves existing integrations. Explicit `skills` and defaults still
load eagerly; other enabled, visible registry skills are advertised as compact
metadata (up to the existing catalog cap). The model uses the automatically
installed `load_skill` tool to read a body. In this mode, automatic phrase-based
eager selection is disabled. Existing applications using that selection can
leave `progressive_skills=False`.

Loader state is fresh per run, not a global set of previously loaded IDs. This
prevents cross-chat contamination and allows reloading after history eviction
or compaction. Duplicate loads within a run return a short acknowledgement.
Cross-run body deduplication is not implemented. `load_skill` is a reserved
name in this mode: a caller-supplied collision raises a configuration error.

Loading instructions does **not** install tools declared by a model-selected
skill or grant permissions. Supply authorized tools/MCPs normally; discovery
can expose their schemas when needed. Never share a tenant's authorized
registry/history with another tenant. Explicit eager skills retain their
existing builtin-tool behavior and permission checks.

## Discovery

Matching remains corpus-weighted lexical retrieval, not an embedding service.
Tool authors may provide `metadata['discovery_terms']` for domain vocabulary
and alternative descriptions. These are authored terms, not hardcoded global
synonym rules. Results identify already-loaded matches and advise calling them
directly. This reduces unnecessary discovery guidance but cannot guarantee a
model never repeats a search.

New tests rank invoice lookup above similarly named send/log tools in 100- and
500-tool catalogs, using three queries including an authored vocabulary alias.
These six checks are a small regression set, not a broad semantic benchmark.

## Budgets and usage diagnostics

`max_task_tokens` is a **soft per-run threshold**, checked between model steps.
Completed provider-reported input (including cached input) and output count.
If a completion omits either normalized input or output usage, budgeted work stops before another step
instead of treating missing usage as free. Results are marked incomplete and
completed tool evidence remains in the session. A positive integer is required.

This is not a hard monetary cap or a session-wide spending limit. An in-flight
request, retry inside a request, tool batch, or summary can overshoot the limit.
Providers may omit usage for failed requests. Use provider account controls
and request/output limits when a strict financial cap is required.

The budget also gates the extra final-summary call after an iteration limit.
Previously that path could spend again after the threshold had been reached.
Regression tests reproduce and fix both this issue and partial usage reports
(input-only, output-only, total-only or cache-only) in sync and async execution.
`budget_usage_complete` reports whether every accounted completion provided
the input/output counters needed for enforcement. This is separate from
`provider_usage_available`, which can be true for a partial report.

2026-09-29 budget audit: the new partial-usage cases reproduced eight failures
and iteration-limit cases reproduced two failures before these fixes. After
fixing both sync/async paths, the full Shipit suite passed **4,514 tests, 31
skipped**, and targeted DRK accounting/streaming integration passed **87 tests**.
A live Gemma 31B run with `max_task_tokens=10000` passed all ten fixture
scenarios: **42,040 input / 391 output tokens**, including **2,368 reported
cache-read tokens**. This demonstrates normal fixture tasks still finish under
the per-turn policy; deterministic regressions exercise the actual cutoff.

`run_summary.usage_diagnostics` contains:

- Estimated main-request content tokens: system, conversation, tool results,
  and schemas. These sum across requests, exclude retry replay and summarizer
  inputs, and are **not an exact partition of provider-billed tokens**.
- Reported main vs. compaction input/output totals; compaction preserves the
  provider adapter's inclusive-cache accounting metadata.
- System/schema prefix-change count, retained in bounded per-session runtime
  state. Content hashes are internal; raw prompts/credentials aren't exposed.
- Whether cache counters and usage were actually reported, plus retry events.

Prefix stability does not prove a cache hit. Provider cache counters remain
the evidence. Cross-worker prefix continuity is not yet persisted by hosts.

## Validation scope

New deterministic coverage includes ordinary Agent loading through run/stream/
async, four concurrent isolated chats, denied loader calls, soft budget stops,
missing-usage stops, cache-prefix changes and roughly 510 KB tool output with a
bounded model view and preserved canonical result.

A real loopback HTTP server tests two concurrent MCP sessions, SSE responses,
session-header affinity, and HTTP 401/429/503 errors. This validates local
transport behavior, **not production tenant authorization or external uptime**.
Provider contracts have deterministic tests; live-provider testing in this pass
uses Gemma 31B on Bedrock only.

The live ten-scenario suite now uses `progressive_skills=True` directly, not a
manually supplied loader. It passed 10/10 with 41,117 input and 340 output
tokens, with no reported cache-read tokens. This does not establish cache
support or lack of support at the endpoint.

A fresh repeat also passed 10/10: 41,830 input and 346 output tokens. All five
explicit history-only/no-tool checks made zero tool calls. The failed-source
scenario made one failed call and correctly distinguished it from an empty
result. No cache counters were present on any of these turns; a stored zero
must not be interpreted as a measured cache miss. This repeat is evidence of
fixture consistency, not production reliability or a statistical success rate.

HTTP coverage additionally verifies mixed outcomes: tenant A completes normally
while tenant B receives 401, 429 or 503. The focused protocol, progressive-skill
and MCP regression set passed 87 tests.

Expanded discovery follow-up: 20 shuffled-catalog checks cover forum chatter,
case evidence, invoices, source code and URL retrieval in 100/500-tool catalogs,
including similarly named deletion tools. All pass. Wording deliberately has
lexical overlap with descriptions; this is not an embedding/paraphrase benchmark.
Together with the existing catalog/HTTP checks, that file passes 34 tests.

The 500-tool offline benchmark completes the same 20 operations with 488,969
serialized request characters in auto mode versus 4,496,472 eager (89.1% less).
Auto uses 22 requests versus 21 eager. Characters are not provider-billed tokens
and the scripted model is not a model-quality evaluation.

2026-09-29 streaming repeat (live Gemma 31B/Bedrock, fixture stdio MCP):
20/20 evidence checks passed; 537 text deltas, six calls with six tool-result
completions, and one compaction. Each turn emitted exactly one final-answer
and run-completed event. All 15 follow-up turns avoided additional tool calls.
Median first-text latency was 1.721 seconds; maximum was 9.748 seconds.
Usage: 70,925 input / 1,146 output tokens. No cache reads were reported.
This verifies event delivery, not smooth provider pacing or production tools.
The focused streaming/provider/progressive/HTTP checks passed 83 tests.

The 40-message Gemma 31B/Bedrock session passed 40/40 evidence checks with
11 tool calls and three compactions under an intentionally small 4,200-token
context setting. It cycles the existing 20-scenario workload over five fixture
cases; it is not 40 distinct tasks or a production-case evaluation.

| Measurement | Observed |
| --- | ---: |
| Input tokens | 148,077 |
| Output tokens | 3,032 |
| Reported cache-read tokens | 1,728 (1.17% of input) |
| Main request tokens (input + output) | 144,910 |
| Compaction tokens (input + output) | 6,199 |
| System/schema prefix changes | 2 |

Only one turn reported cache counters. Missing counters cannot establish cache
misses, and stable system/schema hashes do not establish that the provider's
whole cacheable prefix stayed stable. No substantial cache savings are claimed.

Final offline regression: **4,477 passed, 31 skipped**, with one existing
collection warning. Targeted DRK discovery/integration checks: **4 passed**.
Changes are not deployed by these tests.

## DRK host integration

DRK already supplies its own authorization-aware `load_skill` and catalog.
Do not enable Shipit's `progressive_skills` there as well: that would collide
with the host loader and bypass neither the need for grants nor tenant checks.
Keep the existing host loader and Shipit's deferred tool discovery.
DRK no longer injects a wrapped builtin `tool_search` alongside this policy;
Shipit creates its discovery tool only when the authorized catalog needs it.

The DRK builder accepts an optional `max_task_tokens` positive integer in the
selected LLM model row's `config` JSON. Omit it or use `null` to preserve current
behavior. For example, `{"max_task_tokens": 50000}` sets a soft threshold for
each turn, not for the whole conversation. Deploy the matching Shipit version
with this constructor option before deploying the host change. No database
migration is required; no production configuration has been changed.

Budget events are mapped to SSE notices; the terminal run summary contains the
incomplete reason and usage diagnostics. DRK's provider meter now respects
`prompt_tokens_include_cache` for ratios and peak context while retaining raw
input counters. Cache-counter report counts distinguish omitted counters from
reported zero. These are token measures, not a percentage monetary saving.

DRK follow-up validation: 63 focused accounting/discovery/MCP/streaming checks
passed. The remaining old report test contradicted the newer rule accepting
explicitly typed case reports. The regression now preserves those reports and
separately verifies unfiling an untyped note without report evidence. No report
classification implementation was changed. Latest full DRK suite: **1,445
passed, 44 skipped** (dependency/test-fixture warnings remain).

Reproduce the longer live evaluation (billed provider calls):

```sh
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py --live --provider bedrock --model google.gemma-4-31b --turns 40 --context-window 4200 --mcp-stdio --report /tmp/new-40turn-report.jsonl
```
