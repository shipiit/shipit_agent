# AgentBenchmark — Systematic Testing

Test your agents systematically with expected outputs, tool usage checks, and detailed pass/fail reports.

## Quick start

```python
from shipit_agent.deep import AgentBenchmark, TestCase

benchmark = AgentBenchmark(
    name="knowledge-eval",
    cases=[
        TestCase(input="What is Python?", expected_contains=["programming"]),
        TestCase(input="What is Docker?", expected_contains=["container"]),
        TestCase(input="Explain REST", expected_contains=["http"], expected_not_contains=["graphql"]),
        TestCase(input="Search for news", expected_tools=["web_search"]),
    ],
)

report = benchmark.run(agent)
print(report.summary())
```

## Output

```
Agent Benchmark: knowledge-eval
Cases: 4 passed, 0 failed (4 total)
Pass rate: 100%
Avg iterations: 1.2
  [PASS] What is Python?
  [PASS] What is Docker?
  [PASS] Explain REST
  [PASS] Search for news
```

## With retry (for Bedrock rate limits)

```python
report = benchmark.run(agent, retry=3, delay=2.0)
```

## TestCase options

| Field | Description |
|---|---|
| `input` | Prompt sent to agent |
| `expected_contains` | Output must contain these words |
| `expected_not_contains` | Output must NOT contain these |
| `expected_tools` | These tools must be used |

## BenchmarkReport

| Property | Description |
|---|---|
| `passed` / `failed` / `total` | Counts |
| `pass_rate` | 0.0 - 1.0 |
| `summary()` | Human-readable report |
| `to_dict()` | JSON export for dashboards |

!!! tip "Notebook"
    `notebooks/15_agent_benchmark.ipynb`
