# Agent efficiency and capability validation — 2026-09-28

Follow-up: [ordinary Agent progressive skills, task budgets and 40-turn results](progressive-agent-controls.md).
The opt-in ordinary Agent loader supersedes the manual-loader setup described
in the earlier measurements below.

## What the research supports

[OpenAI skill documentation](https://developers.openai.com/api/docs/guides/tools-skills)
describes advertising skill metadata first, then reading instructions and
supporting files when the task needs them. This is not a reason to send every
skill body with every question.

[Claude Code skills](https://code.claude.com/docs/en/skills) also document
on-demand loading and avoiding duplicate copies of unchanged loaded content.
[Claude Code MCP](https://code.claude.com/docs/en/mcp) documents deferred tool
definitions and provider-dependent fallback. Shipit's portable discovery uses
ordinary function schemas; it is not Anthropic's native tool-reference protocol.
These are documented design patterns, not a claim of equivalent model quality.

## Changes in this pass

- Identical guidance is emitted once per tool family, with the exact tool names
  it applies to. Different constraints are never merged by similarity.
- Prompt construction reuses the skills already selected for the run instead
  of rescanning the catalog. When their tools are already supplied, it skips
  constructing the entire builtin collection.
- Skills cannot overwrite host-supplied tools with same-named builtins. This
  preserves application-specific implementations, including tenant scoping.
- Skill catalog descriptions respect the configured character budget; loaded
  instructions retain the existing body budget and behavior.
- `LoadSkillTool` declares read-only behavior and a discovery priority so its
  small schema is preferred in the initial working set. It still competes
  within the configured budget and is not exempt from permissions.
- Skill references use resolved path containment, rejecting sibling-prefix and
  symlink escapes. No script execution or new privileges are introduced.
- Compaction retains at least the newest user turn when the fixed prefix
  exceeds the nominal retention target. Previously, that case could prevent
  any summary and force repeated history trimming instead.

The ordinary Agent's explicit/trigger-based skill path remains supported.
The live test supplies `LoadSkillTool` and a scoped `SkillSession` explicitly;
this does not claim all Agent registries automatically use progressive loading.
Do not share mutable skill sessions across unrelated chats.

## Deterministic coverage

Both `tests/` and `shipit_agent/tests/` were included: **4,452 passed, 31 skipped**,
one existing collection warning. Manual live harnesses and the notebook test
were excluded. Coverage includes sync/async runtime, streaming, permissions,
MCP schema/cache/reconnect/failure paths, recovery, compaction, plugins and skills.
Not every transport/provider combination was tested against a live service.
Four targeted DRK integration tests also passed. After the builtin-construction
optimization, 71 skill/workspace tests passed; the compaction fix passed 67
compaction/context/async tests before the final full rerun.

New regressions cover grouped guidance with distinct constraints, preservation
of host tools, reference-path escapes, metadata/body separation, duplicate skill
load results, reuse of skill selection and loader residency. A durable-history
test now uses an acknowledgement stub rather than echoing the entire system
prompt back as an answer, which had triggered tool-call recovery.

## Live Gemma 31B / Bedrock results

All tool data is synthetic. MCP uses a real local stdio subprocess; no production
case systems are contacted. Provider calls are real and billed.

The ten-scenario suite covers arithmetic without tools, MCP discovery, history
reuse, skill loading, missing records, missing-record follow-up, a failed source,
error recall, cross-case retrieval and final arithmetic from prior evidence.
Checks assert exact fixture values/format and absence of tools when prohibited;
they are not a comprehensive subjective answer-quality evaluation.

| Trial | Checks | Input | Output | Notes |
| --- | ---: | ---: | ---: | --- |
| Initial capability test | 9/10 | 40,634 | 459 | Model searched for skill ID as a tool; did not load skill |
| Same prompts after loader priority fix | 10/10 | 41,285 | 318 | Skill loaded and format followed; no-tool follow-ups made no calls |
| 20-message recall session, 4,200-token budget | 20/20 | 70,864 | 630 | One discovery + five MCP lookups; no completed compaction |
| Tighter 3,200-token session before boundary fix | 20/20 | 69,839 | 536 | Three hard-fit events, no summarizer calls; exposed retention-target bug |
| Same 3,200-token session after boundary fix | 20/20 | 62,939 | 1,779 | Three actual summaries; all cross-turn fixture checks retained |

The last session reported 4,880 cache-read tokens, included in input rather than
added again. The previous successful 20-turn sample used 76,964 input tokens;
this sample uses about 7.9% fewer. That is an observation, not an isolated causal
benchmark: generation length, caching and whether compaction runs also vary.
The skill fix deliberately spent slightly more input to complete the task.
The tighter-budget rerun spent more output on summaries but reduced total tokens
from 70,375 to 64,718 (about 8.0%) in these samples. Different runs can vary.

## Offline payload benchmark

With the same code, twenty fixture operations and synthetic catalogs:

| Catalog size | Eager request characters | Auto request characters | Reduction |
| --- | ---: | ---: | ---: |
| 10 | 380,535 | 380,535 | 0% |
| 30 | 546,645 | 486,527 | 11.0% |
| 100 | 1,127,337 | 486,548 | 56.8% |

These count serialized harness requests, not provider-billed tokens. The
benchmark includes discovery's extra model request. Lower percentages than an
older benchmark are expected when shared-guidance deduplication also improves
the eager baseline.

## Reproduce

```sh
.venv/bin/pytest -q tests shipit_agent/tests --ignore=tests/live --ignore=tests/test_agent_mcp_token_stream_notebook.py
PYTHONPATH=. .venv/bin/python scripts/benchmark_tool_discovery.py
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_capabilities.py --live --report /tmp/new-capability-report.jsonl
PYTHONPATH=. .venv/bin/python scripts/evaluate_agent_session.py --live --provider bedrock --model google.gemma-4-31b --turns 20 --context-window 3200 --mcp-stdio --report /tmp/new-compaction-report.jsonl
```

Live reports use exclusive creation, keep failed cases, and never print API keys.
Remaining evaluation work includes repeated statistical trials, live HTTP/SSE
MCP services, other provider models, larger skill catalogs with paraphrased
requests, and application-specific production authorization boundaries.
