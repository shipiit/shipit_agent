"""Compare benchmark runs side by side: which model used more tokens, turns and money.

    python -m scripts.bench.compare bench-gemma.json bench-gpt-oss.json bench-claude.json

Each file is one run's JSON from scripts.bench.run. Per task it shows each
model's input tokens (with a ✗ where the task failed) and marks the
lowest; below, each model's totals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


Rows = dict[str, list[dict[str, Any]]]


def load(path: str) -> tuple[str, Rows]:
    """The run's model name, and its rows grouped by task (several with --repeat)."""
    data = json.loads(Path(path).read_text())
    by_task: Rows = {}
    for row in data["rows"]:
        by_task.setdefault(row["task"], []).append(row)
    return str(data.get("model") or Path(path).stem), by_task


def typical(runs: list[dict[str, Any]], key: str) -> float:
    """The median of *key* over the runs that passed, or over all when none did."""
    passing = [r for r in runs if r["passed"]] or runs
    return float(median((r.get(key) or 0) for r in passing))


def totals(rows: Rows) -> dict[str, Any]:
    """Each task's typical figures, summed, so runs with different repeats compare."""
    def total(key: str) -> float:
        return sum(typical(runs, key) for runs in rows.values())

    return {
        "passed": f"{sum(r['passed'] for runs in rows.values() for r in runs)}"
                  f"/{sum(len(runs) for runs in rows.values())}",
        "input_tokens": total("input_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "output_tokens": total("output_tokens"),
        "turns": total("turns"),
        "cost_usd": total("cost_usd"),
        "api_s": total("api_ms") / 1000,
        # Older result files have neither.
        "narration_chars": total("narration_chars"),
        "thinking_chars": total("thinking_chars"),
    }


def _cell(runs: list[dict[str, Any]] | None, best: float | None, width: int) -> str:
    if not runs:
        return f"{'-':>{width}}"
    tokens = typical(runs, "input_tokens")
    passes = sum(r["passed"] for r in runs)
    if len(runs) > 1:
        mark = "★" if passes and tokens == best else " "
        return f"{f'{tokens:,.0f} {passes}/{len(runs)}':>{width - 2}} {mark}"
    mark = "✗" if not passes else ("★" if tokens == best else " ")
    return f"{tokens:>{width - 2},.0f} {mark}"


def compare(runs: list[tuple[str, Rows]]) -> str:
    names = [name for name, _ in runs]
    width = max(14, *(len(n) for n in names))
    tasks = list(dict.fromkeys(task for _, rows in runs for task in rows))
    lines = ["Input tokens per task: the median of passing runs, with passes/runs when repeated",
             "(★ fewest among runs that passed, ✗ failed)",
             f"{'task':20} " + " ".join(f"{n:>{width}}" for n in names)]
    for task in tasks:
        cells = [rows.get(task) for _, rows in runs]
        passing = [typical(c, "input_tokens") for c in cells if c and any(r["passed"] for r in c)]
        best = min(passing) if passing else None
        lines.append(f"{task:20} " + " ".join(_cell(c, best, width) for c in cells))
    sums = [totals(rows) for _, rows in runs]
    lines += ["", f"{'totals':20} " + " ".join(f"{n:>{width}}" for n in names)]
    for key, label, fmt in [("passed", "passed", "{}"), ("input_tokens", "input tokens", "{:,.0f}"),
                            ("cached_input_tokens", "  of which cached", "{:,.0f}"),
                            ("output_tokens", "output tokens", "{:,.0f}"), ("turns", "turns", "{:.0f}"),
                            ("cost_usd", "cost $", "{:.4f}"), ("api_s", "model seconds", "{:.1f}"),
                            ("narration_chars", "text beside calls", "{:,.0f}"),
                            ("thinking_chars", "visible thinking", "{:,.0f}")]:
        lines.append(f"{label:20} " + " ".join(f"{fmt.format(s[key]):>{width}}" for s in sums))
    most = max(range(len(sums)), key=lambda i: sums[i]["input_tokens"])
    least = min(range(len(sums)), key=lambda i: sums[i]["input_tokens"])
    if most != least:
        ratio = sums[most]["input_tokens"] / max(sums[least]["input_tokens"], 1)
        lines += ["", f"Most input tokens: {names[most]}, {ratio:.2f}x {names[least]}'s."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="JSON results from scripts.bench.run")
    print(compare([load(path) for path in parser.parse_args().files]))


if __name__ == "__main__":
    main()
