# The benchmark

`scripts/bench` runs real tasks through `shipit_agent.sdk.query` and judges
each one by what it leaves behind: the repository's tests pass, the hook
really blocked the delete, nothing was written before approval. An answer
that only *mentions* the right word does not pass.

Use it to compare models, and to check that a change to prompts, tools or
the loop makes the agent no worse and no more expensive.

## Run it

From the repository root:

```bash
python -m scripts.bench.run --dry-run                              # wiring only, no model, free
python -m scripts.bench.run bedrock google.gemma-4-31b             # all tasks on one model
python -m scripts.bench.run anthropic claude-sonnet-5-5 --out bench-claude.json
python -m scripts.bench.run bedrock google.gemma-4-31b --tasks fix_failing_test,cross_module_bug
```

The first argument is the provider, the second the model id; credentials
come from the environment as for any shipit agent. Each task runs in a fresh
temporary folder and is capped at 12 turns (40 for the two long tasks) and
$0.25. The shells it starts
get the benchmark's own Python first on `PATH`, as an activated virtualenv
would.

`--clear-tool-results TOKENS` turns on clearing of old tool results for every
task, starting at that many tokens; run once with it and once without to
see what it saves.

`--repeat N` runs each task N times. The comparison then shows each task's
median input tokens over its passing runs, with passes out of runs (`2/3`),
and sums the medians, so a repeated run compares fairly with a single one.

To compare runs:

```bash
python -m scripts.bench.compare bench-gemma.json bench-gptoss.json bench-claude.json
```

It prints each task's input tokens per model (★ the fewest among runs that
passed, ✗ a failure) and each model's totals.

## The tasks

| Task | Feature | Passes only if |
| :- | :- | :- |
| `fix_failing_test` | files + bash | the repo's tests pass afterwards |
| `find_definition` | search | the answer names the right file and default |
| `mcp_in_process` | MCP, in-process | the answer has the tool's figure and decision |
| `mcp_stdio` | MCP, stdio server | the answer has the external server's record |
| `plugin_command` | plugin command | the plugin's `/command` gives the right count |
| `plugin_skill` | plugin skill | the skill's exact output appears |
| `hook_blocks_delete` | hooks | a delete was attempted, the hook blocked it, `build/` survives |
| `background_task` | background tasks | other work ran meanwhile, then the task's result was used |
| `subagent` | sub-agents | the defined agent was used and the count is right |
| `structured_output` | structured output | the parsed JSON matches |
| `deferred_approval` | deferred approval | nothing written until approval, written after resume |
| `ask_user` | clarifying questions | the question was asked and the answer used |
| `multi_turn_memory` | multi-turn client | turn two is answered from turn one, without reading again |
| `cross_module_bug` | files + bash | a bug in another module is fixed where it lives |
| `tool_error_recovery` | MCP errors | after a rejected id, a retry succeeds |
| `needle_in_log` | large files | one line of a 6,000-line log, by number |
| `rename_across_modules` | long: refactor | a function renamed across eight modules and tests; tests pass, old name gone |
| `add_feature` | long: feature | coupons implemented from a spec; the prewritten tests pass |

Connectors that need real accounts (Slack, Jira, ...) are not covered.

## Reading a row

Per task: passed, turns, input and output tokens, cost, model time, wall
time, tool calls, tool errors, and repeated calls (the same call again with
nothing changed in between; running the tests again after an edit is not a
repeat). The JSON adds the final answer, the text the model wrote beside
its calls, any visible thinking, and a trace of every call with the start
of its result: when a task takes more turns than it should, the trace shows
where they went. A run that ended in error reports the error itself.

A single run varies: the same model's totals moved by up to 20% between two
runs. Use `--repeat 3` or more before reading differences of a few percent,
and remember each model counts tokens with its own tokenizer.

## Adding a task

A task is a `Task(name, feature, prompt, options, check)` in
`tasks_basic.py`, `tasks_control.py` or `tasks_hard.py`:

- `options(root)` returns extra `AgentOptions` for the task;
- `check(run)` returns `(passed, note)` from what the run left behind: files
  in `run.root`, `run.result`, `run.tool_uses`;
- `setup(root)` builds the workspace (default: a small repository);
- `custom(task, run_query, root)` drives several queries (a resume, a client).

`tests/test_bench_wiring.py` runs every task with the echo model, so a broken
task fails the suite before it costs anything.

## Pitfalls

- **Claude needs the `anthropic` package.** Without it the Anthropic adapter
  raises at the first call. (It used to answer with gpt-oss on Bedrock
  instead, which made a "Claude" run silently test another model.)
- **zsh does not split variables into words**, so `B="python -m ..."; $B`
  fails; use a shell function to run several models in one line.
