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
from typing import Any


def load(path: str) -> tuple[str, dict[str, dict[str, Any]]]:
    data = json.loads(Path(path).read_text())
    return str(data.get("model") or Path(path).stem), {row["task"]: row for row in data["rows"]}


def totals(rows: dict[str, dict[str, Any]]) -> dict[str, float]:
    values = list(rows.values())
    return {
        "passed": sum(r["passed"] for r in values),
        "tasks": len(values),
        "input_tokens": sum(r["input_tokens"] for r in values),
        "output_tokens": sum(r["output_tokens"] for r in values),
        "turns": sum(r["turns"] for r in values),
        "cost_usd": sum(r["cost_usd"] or 0 for r in values),
        "api_s": sum(r["api_ms"] for r in values) / 1000,
    }


def compare(runs: list[tuple[str, dict[str, dict[str, Any]]]]) -> str:
    names = [name for name, _ in runs]
    width = max(14, *(len(n) for n in names))
    tasks = list(dict.fromkeys(task for _, rows in runs for task in rows))
    lines = ["Input tokens per task (★ fewest among runs that passed, ✗ failed)",
             f"{'task':20} " + " ".join(f"{n:>{width}}" for n in names)]
    for task in tasks:
        cells = [rows.get(task) for _, rows in runs]
        passing = [c["input_tokens"] for c in cells if c and c["passed"]]
        best = min(passing) if passing else None
        shown = []
        for cell in cells:
            if cell is None:
                shown.append(f"{'-':>{width}}")
                continue
            mark = "✗" if not cell["passed"] else ("★" if cell["input_tokens"] == best else " ")
            shown.append(f"{cell['input_tokens']:>{width - 2},} {mark}")
        lines.append(f"{task:20} " + " ".join(shown))
    sums = [totals(rows) for _, rows in runs]
    lines += ["", f"{'totals':20} " + " ".join(f"{n:>{width}}" for n in names)]
    for key, label, fmt in [("passed", "passed", "{:.0f}"), ("input_tokens", "input tokens", "{:,.0f}"),
                            ("output_tokens", "output tokens", "{:,.0f}"), ("turns", "turns", "{:.0f}"),
                            ("cost_usd", "cost $", "{:.4f}"), ("api_s", "model seconds", "{:.1f}")]:
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
