"""Run the shipit agent benchmark: real tasks, checked by what they leave behind.

    python -m scripts.bench.run bedrock google.gemma-4-31b
    python -m scripts.bench.run anthropic claude-sonnet-5-5 --tasks mcp_stdio,subagent
    python -m scripts.bench.run --dry-run      # wiring only, no model, no cost

Run it from the repository root. The task shells get this interpreter's
folder first on PATH, as an activated virtualenv would, so `python` and
`pytest` there are the ones this run uses.

Each task gets a fresh synthetic workspace in a temp folder and runs through
shipit_agent.sdk.query with at most 12 turns and $0.25. Reported per task:
passed, turns, input and output tokens, cost, model time, wall time, tool
calls, tool errors and repeated identical calls. Results also go to a JSON
file, so runs on different models or versions can be compared.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from shipit_agent.sdk import AgentOptions, query

from .tasks_basic import BASIC_TASKS, Run, Task
from .tasks_control import CONTROL_TASKS
from .tasks_hard import HARD_TASKS
from .tasks_long import LONG_TASKS

TASKS = BASIC_TASKS + CONTROL_TASKS + HARD_TASKS + LONG_TASKS


def build_llm(provider: str | None, model: str | None, dry_run: bool) -> Any:
    if dry_run:
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()
    from shipit_agent.llms.factory import build_llm_from_settings

    return build_llm_from_settings({"model": model} if model else None, provider=provider)


class Runner:
    """Runs one prompt as a query; tasks that drive a client use its options."""

    def __init__(self, llm: Any, agent_options: dict[str, Any] | None = None) -> None:
        self.llm = llm
        #: Agent settings applied to every task, e.g. to compare clearing on and off.
        self.agent_options = dict(agent_options or {})

    def options(self, extra: dict[str, Any], root: Path) -> AgentOptions:
        settings = {"llm": self.llm, "cwd": root, "max_turns": 12, "max_budget_usd": 0.25, **extra}
        settings["agent_options"] = {**self.agent_options, **settings.get("agent_options", {})}
        return AgentOptions(**settings)

    async def __call__(self, prompt: str, extra: dict[str, Any], root: Path) -> Run:
        run = Run(root=root)
        async for message in query(prompt=prompt, options=self.options(extra, root)):
            run.record(message)
        return run


def make_runner(llm: Any, agent_options: dict[str, Any] | None = None) -> Runner:
    return Runner(llm, agent_options)


async def run_task(task: Task, run_query: Any) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"bench-{task.name}-") as folder:
        root = Path(folder)
        task.setup(root)
        try:
            if task.custom is not None:
                run = await task.custom(task, run_query, root)
            else:
                run = await run_query(task.prompt, task.options(root), root)
            passed, note = task.check(run)
        except Exception as error:  # a crashed task is a failed task, reported with its error
            return _row(task, None, False, f"{type(error).__name__}: {error}", started)
        return _row(task, run, passed, note, started)


async def run_tasks(tasks: list[Task], run_query: Any, *, repeat: int = 1, verbose: bool = False) -> list[dict[str, Any]]:
    """Each task *repeat* times, in order; each row says which trial it was."""
    rows = []
    for task in tasks:
        for trial in range(repeat):
            row = {**await run_task(task, run_query), "trial": trial}
            rows.append(row)
            if verbose:
                label = f"{task.name} #{trial + 1}" if repeat > 1 else task.name
                print(f"  {label}: {'passed' if row['passed'] else 'failed'} ({row['note'][:70]})", flush=True)
    return rows


def _row(task: Task, run: Run | None, passed: bool, note: str, started: float) -> dict[str, Any]:
    result = run.result if run else None
    results = run.results if run else []
    errors = [e for r in results if r.is_error for e in r.errors]
    if errors:  # the check saw an empty answer; the reason is the run's own error
        passed, note = False, f"run error: {errors[0]}"
    calls = [(name, json.dumps(args, sort_keys=True)) for name, args in (run.tool_uses if run else [])]
    return {
        "task": task.name, "feature": task.feature, "passed": bool(passed), "note": note,
        "subtype": getattr(result, "subtype", None),
        "turns": sum(r.num_turns for r in results),
        "input_tokens": sum(_total_input(r.usage or {}) for r in results),
        "cached_input_tokens": sum(int((r.usage or {}).get("cache_read_input_tokens") or 0) for r in results),
        "output_tokens": _tokens(results, "output_tokens", "completion_tokens"),
        "cost_usd": _cost(results),
        "api_ms": sum(r.duration_api_ms for r in results),
        "wall_s": round(time.monotonic() - started, 1),
        "tool_calls": len(calls),
        "tool_errors": run.tool_errors if run else 0,
        "repeated_calls": repeated_calls(run.tool_uses if run else []),
        "unmatched_results": run.unmatched_results if run else 0,
        "narration_chars": run.narration_chars if run else 0,
        "thinking_chars": run.thinking_chars if run else 0,
        "answer": (run.answer if run else "")[:500],
        "trace": _trace(run),
    }


def _tokens(results: list[Any], *keys: str) -> int:
    """Summed over turns, under whichever name the provider's usage uses."""
    total = 0
    for result in results:
        usage = result.usage or {}
        total += int(next((usage[k] for k in keys if usage.get(k)), 0))
    return total


def _total_input(usage: dict[str, Any]) -> int:
    """All input: the SDK-shaped fields when present, else the provider's prompt_tokens."""
    if "input_tokens" in usage:
        return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                    "cache_creation_input_tokens"))
    return int(usage.get("prompt_tokens") or 0)


def _cost(results: list[Any]) -> float | None:
    costs = [r.total_cost_usd for r in results if r.total_cost_usd is not None]
    return round(sum(costs), 6) if costs else None


#: Calls that only look; anything else may change what a later call returns.
_LOOK_ONLY = frozenset({"read_file", "glob_files", "grep_files", "todo", "web_search", "open_url"})


def repeated_calls(tool_uses: list[tuple[str, dict[str, Any]]]) -> int:
    """Identical calls made again with nothing changed in between.

    Running the tests again after an edit is a check, not a repeat: any call
    that may change something (an edit, a write, a command) starts afresh.
    """
    seen: set[tuple[str, str]] = set()
    repeats = 0
    for name, args in tool_uses:
        key = (name, json.dumps(args, sort_keys=True))
        repeats += key in seen
        seen = seen | {key} if name in _LOOK_ONLY else {key}
    return repeats


def _trace(run: Run | None) -> list[dict[str, Any]]:
    """Each call with its arguments and the start of its result, to see where turns went."""
    if run is None:
        return []
    trace = []
    for index, (name, args) in enumerate(run.tool_uses):
        output, failed = run.tool_results[index] if index < len(run.tool_results) else ("", False)
        trace.append({"tool": name, "args": json.dumps(args)[:160], "error": failed,
                      "result": " ".join(output.split())[:160]})
    return trace


def report(rows: list[dict[str, Any]], label: str) -> str:
    head = f"{'task':20} {'ok':3} {'turns':>5} {'in tok':>8} {'out':>6} {'cost $':>8} {'api s':>6} {'calls':>5} {'err':>4} {'rep':>4}  note"
    lines = [f"shipit agent benchmark: {label}", head, "-" * len(head)]
    for r in rows:
        cost = f"{r['cost_usd']:.4f}" if r["cost_usd"] else "-"
        lines.append(f"{r['task']:20} {'✓' if r['passed'] else '✗':3} {r['turns']:>5} {r['input_tokens']:>8,} "
                     f"{r['output_tokens']:>6,} {cost:>8} {r['api_ms'] / 1000:>6.1f} {r['tool_calls']:>5} "
                     f"{r['tool_errors']:>4} {r['repeated_calls']:>4}  {r['note'][:60]}")
    passed = sum(r["passed"] for r in rows)
    total_cost = sum(r["cost_usd"] or 0 for r in rows)
    total_in = sum(r["input_tokens"] for r in rows)
    lines += ["-" * len(head), f"passed {passed}/{len(rows)} · input tokens {total_in:,} · cost ${total_cost:.4f}"]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("provider", nargs="?", help="bedrock, anthropic, openai, ... (default: from env)")
    parser.add_argument("model", nargs="?", help="a model id (default: the provider's)")
    parser.add_argument("--tasks", help="comma-separated task names (default: all)")
    parser.add_argument("--out", default="bench-results.json", help="where to write the JSON results")
    parser.add_argument("--dry-run", action="store_true", help="check the wiring with an echo model; no cost")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run each task N times; compare.py then reads medians")
    parser.add_argument("--clear-tool-results", type=int, metavar="TOKENS",
                        help="clear old tool results once they pass TOKENS (off by default)")
    args = parser.parse_args()
    os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    chosen = [t for t in TASKS if not args.tasks or t.name in args.tasks.split(",")]
    llm = build_llm(args.provider, args.model, args.dry_run)
    label = "dry run (echo model)" if args.dry_run else str(getattr(llm, "model", args.model or "default"))
    agent_options = {}
    if args.clear_tool_results:
        from shipit_agent.context.tool_result_clearing import ToolResultClearing

        agent_options["clear_tool_results"] = ToolResultClearing(trigger_tokens=args.clear_tool_results)
        label += f" · clearing at {args.clear_tool_results:,} tokens"
    run_query = make_runner(llm, agent_options)
    rows = await run_tasks(chosen, run_query, repeat=args.repeat, verbose=True)
    print("\n" + report(rows, label))
    Path(args.out).write_text(json.dumps({"model": label, "rows": rows}, indent=2))
    print(f"\nresults: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
