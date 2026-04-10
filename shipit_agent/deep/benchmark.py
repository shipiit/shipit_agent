from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TestCase:
    """A single test case for agent benchmarking."""

    input: str
    expected_tools: list[str] = field(default_factory=list)
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    max_iterations: int = 10
    max_tokens: int = 0  # 0 = no limit


@dataclass(slots=True)
class TestResult:
    """Result of running a single test case."""

    test_case: TestCase
    passed: bool
    output: str = ""
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    failures: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkReport:
    """Summary report of a benchmark run."""

    name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def summary(self) -> str:
        avg_iters = sum(r.iterations for r in self.results) / self.total if self.total else 0
        tool_counts = {}
        for r in self.results:
            for t in r.tools_used:
                tool_counts[t] = tool_counts.get(t, 0) + 1

        lines = [
            f"Agent Benchmark: {self.name}",
            f"Cases: {self.passed} passed, {self.failed} failed ({self.total} total)",
            f"Pass rate: {self.pass_rate:.0%}",
            f"Avg iterations: {avg_iters:.1f}",
        ]
        if tool_counts:
            lines.append(f"Tools used: {', '.join(f'{k}({v})' for k, v in tool_counts.items())}")

        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{status}] {r.test_case.input[:60]}")
            for f in r.failures:
                lines.append(f"         {f}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "pass_rate": self.pass_rate,
            "results": [
                {
                    "input": r.test_case.input[:100],
                    "passed": r.passed,
                    "tools_used": r.tools_used,
                    "failures": r.failures,
                }
                for r in self.results
            ],
        }


class AgentBenchmark:
    """Benchmark framework for systematically testing agents.

    Example::

        benchmark = AgentBenchmark(
            name="support-agent-eval",
            cases=[
                TestCase(
                    input="How do I reset my password?",
                    expected_contains=["password", "reset"],
                ),
                TestCase(
                    input="Refund order #12345",
                    expected_tools=["order_lookup"],
                ),
            ],
        )
        report = benchmark.run(agent)
        print(report.summary())
    """

    def __init__(self, *, name: str, cases: list[TestCase]) -> None:
        self.name = name
        self.cases = cases

    def run(self, agent: Any) -> BenchmarkReport:
        report = BenchmarkReport(name=self.name)

        for case in self.cases:
            result = agent.run(case.input)
            failures: list[str] = []

            # Check expected content
            output_lower = result.output.lower()
            for expected in case.expected_contains:
                if expected.lower() not in output_lower:
                    failures.append(f"Missing expected content: '{expected}'")

            for unexpected in case.expected_not_contains:
                if unexpected.lower() in output_lower:
                    failures.append(f"Contains unexpected content: '{unexpected}'")

            # Check expected tools
            tools_used = [tr.name for tr in result.tool_results]
            for expected_tool in case.expected_tools:
                if expected_tool not in tools_used:
                    failures.append(f"Expected tool not used: '{expected_tool}'")

            test_result = TestResult(
                test_case=case,
                passed=len(failures) == 0,
                output=result.output,
                tools_used=tools_used,
                iterations=len([e for e in result.events if e.type == "step_started"]),
                failures=failures,
            )
            report.results.append(test_result)

        return report
