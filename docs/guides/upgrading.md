# Upgrading from 2.2

This release brings shipit's defaults in line with how the Claude Agent SDK
and Claude Code behave. Most code keeps working unchanged; the changes
below are the ones that can alter what an existing agent does. Each says
how to get the old behaviour back.

## The run loop

**No step limit by default.** A run ends when the model answers without
calling a tool. `max_iterations` was 12 on `Agent` and 4 on the runtimes;
it is now `None`.

```python
Agent(llm=llm, max_iterations=12)          # the old cap
Agent(llm=llm, max_budget_usd=0.50)        # or cap the spend instead
```

A budgeted run on a model with no pricing data stops with
`budget_cost_unavailable` rather than spend unchecked.

**Read-only calls run in parallel.** `parallel_tool_execution` defaults to
`True`. Only groups in which every call is read-only fan out; a write keeps
its order. Pass `parallel_tool_execution=False` to run every call in turn.

**No automatic planner.** `RouterPolicy.auto_plan` defaults to `False`, so
`plan_task` no longer runs before the first step of a long prompt. The model
can still call it. Use `RouterPolicy(auto_plan=True)` for the old behaviour.

## Tools

**A smaller resident set.** With `deferred_tools="auto"` the tools always in
the prompt are Claude Code's working set (files, glob, grep, bash, web
search and fetch, todo, ask the user, multi_edit, memory, load_skill); the
rest are found through `tool_search`. A tool's `discovery_priority` still
keeps it resident.

**Bash.** The default timeout is 120 s (was 30 s). A command still running
at its timeout keeps going as a background job instead of being killed. A
command that does nothing (`:` or `true` on its own) is refused, with a note
telling the model to put the real command there.

**Shorter guidance.** Each core tool's guidance in the system prompt is now
what it does plus the rules that prevent mistakes; the "when to use",
"decision tree" and "anti-patterns" sections are gone, and the base prompt
says each rule once. The fixed prompt a default agent sends on every turn
is about 42% smaller (~6,440 to ~3,710 tokens). If you pass your own
`prompt=` to a tool, nothing changes for that tool.

**New: clearing old tool results.** `Agent(clear_tool_results=True)` drops
old tool results from each request on long tasks (the history keeps them).
Off by default; see [context management](context-management.md).

**Skills load on demand.** `progressive_skills` defaults to `True`: the prompt
lists each skill in one line and the model loads one with `load_skill`.
Skills named in `skills=[...]` are still applied in full. The packaged
marketplace skills are listed only with `advertise_packaged_skills=True`.

## Providers

**No silent switch away from Anthropic.** Without the `anthropic` package,
`AnthropicChatLLM` used to answer with gpt-oss-120b on Bedrock instead, even
for an explicit `provider="anthropic"`, and the run's cost was computed at
Claude's prices. It now raises at the first call, naming the fix:

```
pip install anthropic          # or: pip install "shipit-agent[anthropic]"
```

**Consecutive user turns are joined for Anthropic.** A message added right
after tool results (a background task's notification) is sent in the same
user message as the results, rather than as a second user turn in a row.

## Permissions

Rules take the SDK's syntax: `Bash(rm *)`, `Bash(npm run test:*)`,
`Edit(src/**)`, `Read(~/.ssh/**)`, `WebFetch(domain:example.com)`,
`mcp__server__*`. SDK tool names (`Bash`, `Read`, `Edit`, ...) name shipit's
tools, so a rule that was a plain glob may now match more calls than
before; check any `deny` or `allow` list you pass.

- `allowed_tools` pre-approves calls; it does not restrict other tools.
- `disallowed_tools` with a bare name removes the tool from the run, so the
  model never sees it. A scoped rule keeps the tool and denies matching
  calls in every mode.
- Bash's guidance tells the model to make a call that needs approval
  rather than ask for permission in text: the runtime (or your hook) asks.
- A `PreToolUse` hook may return `permissionDecision: "defer"`. The run then
  stops with `stop_reason == "tool_deferred"` and the call in
  `result.deferred_tool_use`; resuming the session runs it after checking it
  again.

## Settings files and plugins

Claude Code settings files (`~/.claude/settings.json`,
`.claude/settings.json`, `.claude/settings.local.json`) are read **only** for
the sources you name, because they can run commands:

```python
AgentOptions(setting_sources=["user", "project", "local"])
```

Plugins load from `AgentOptions(plugins=[{"type": "local", "path": ...}])` or
`Agent(harness=Harness.load(...))`.

## The chat CLI

`shipit chat` prints a compact transcript by default: one line per tool call
and a short result under it. `/style modern`, `/style rich` or `/style plain`
switches back for the session.

## Checking an upgrade

The benchmark runs real tasks against a model and reports what each cost;
see [the benchmark guide](benchmark.md):

```
python -m scripts.bench.run --dry-run                    # wiring only, free
python -m scripts.bench.run bedrock google.gemma-4-31b   # a live run
```
