# Cost Tracking & Budgets

Real-time per-call cost tracking with budget enforcement, model-specific pricing, cache savings, and automatic hook integration. Know exactly what every agent run costs.

## Quick start

```python
from shipit_agent import Agent
from shipit_agent.costs import CostTracker, Budget

tracker = CostTracker(budget=Budget(max_dollars=5.00))
agent = Agent.with_builtins(llm=llm, hooks=tracker.as_hooks())

result = agent.run("Analyze this codebase")

print(f"Total cost: ${tracker.total_cost:.4f}")
print(f"Tokens: {tracker.total_tokens}")
```

## How pricing works

`CostTracker` uses a built-in pricing table (`MODEL_PRICING`) with per-million-token prices in USD. Prices cover input tokens, output tokens, and Anthropic prompt cache tokens.

```python
from shipit_agent.costs.pricing import MODEL_PRICING

# See all supported models
for model, prices in MODEL_PRICING.items():
    print(f"{model}: ${prices.get('input', 0)}/M in, ${prices.get('output', 0)}/M out")
```

### Supported models

These are the prices in `shipit_agent/costs/pricing.py`, which the cost tracker uses:

| Provider | Model | Input $/M | Output $/M | Cache read $/M | Cache write $/M |
| :- | :- | -: | -: | -: | -: |
| Anthropic | `claude-fable-5` | 10.00 | 50.00 | 1.00 | 12.50 |
| Anthropic | `claude-fable-5-1` | 10.00 | 50.00 | 0.25 | 12.50 |
| Anthropic | `claude-haiku-4` | 0.80 | 4.00 | 0.08 | 1.00 |
| Anthropic | `claude-haiku-4-20250514` | 0.80 | 4.00 | 0.08 | 1.00 |
| Anthropic | `claude-haiku-4-5` | 1.00 | 5.00 | 0.10 | 1.25 |
| Anthropic | `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 | 0.12 |
| Anthropic | `claude-mythos-5` | 10.00 | 50.00 | 1.00 | 12.50 |
| Anthropic | `claude-mythos-5-1` | 10.00 | 50.00 | 0.25 | 12.50 |
| Anthropic | `claude-opus-4` | 15.00 | 75.00 | 1.50 | 18.75 |
| Anthropic | `claude-opus-4-20250514` | 15.00 | 75.00 | 1.50 | 18.75 |
| Anthropic | `claude-opus-4-6` | 5.00 | 25.00 | 0.50 | 6.25 |
| Anthropic | `claude-opus-4-7` | 5.00 | 25.00 | 0.50 | 6.25 |
| Anthropic | `claude-opus-4-8` | 5.00 | 25.00 | 0.50 | 6.25 |
| Anthropic | `claude-opus-5` | 5.00 | 25.00 | 0.50 | 6.25 |
| Anthropic | `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | 5.00 |
| Anthropic | `claude-sonnet-4` | 3.00 | 15.00 | 0.30 | 3.75 |
| Anthropic | `claude-sonnet-5-5` | 3.00 | 15.00 | 0.30 | 3.75 |
| Anthropic | `claude-sonnet-4-6` | 3.00 | 15.00 | 0.30 | 3.75 |
| Anthropic | `claude-sonnet-5` | 2.00 | 10.00 | 0.20 | 2.50 |
| Anthropic | `claude-sonnet-5-5` | 2.00 | 10.00 | 0.20 | 2.50 |
| Google | `gemini-2.0-flash` | 0.10 | 0.40 | -- | -- |
| Google | `gemini-2.5-flash` | 0.15 | 0.60 | -- | -- |
| Google | `gemini-2.5-pro` | 1.25 | 10.00 | -- | -- |
| Meta / open | `llama-4-maverick` | 0.50 | 0.77 | -- | -- |
| Meta / open | `llama-4-scout` | 0.11 | 0.34 | -- | -- |
| OpenAI | `gpt-4.1` | 2.00 | 8.00 | -- | -- |
| OpenAI | `gpt-4.1-mini` | 0.40 | 1.60 | -- | -- |
| OpenAI | `gpt-4.1-nano` | 0.10 | 0.40 | -- | -- |
| OpenAI | `gpt-4o` | 2.50 | 10.00 | -- | -- |
| OpenAI | `gpt-5.5` | 0.15 | 0.60 | -- | -- |
| OpenAI | `gpt-oss-120b` | 0.15 | 0.60 | -- | -- |
| OpenAI | `gpt-oss-20b` | 0.07 | 0.30 | -- | -- |
| OpenAI | `o3` | 10.00 | 40.00 | -- | -- |
| OpenAI | `o3-mini` | 1.10 | 4.40 | -- | -- |
| OpenAI | `o4-mini` | 1.10 | 4.40 | -- | -- |
| Other | `anthropic.claude-haiku-4-20250514-v1:0` | 0.80 | 4.00 | 0.08 | 1.00 |
| Other | `anthropic.claude-sonnet-5-5-v1:0` | 3.00 | 15.00 | 0.30 | 3.75 |
| Other | `google.gemma-4-26b-a4b` | 0.13 | 0.40 | 0.03 | 0.00 |
| Other | `google.gemma-4-31b` | 0.14 | 0.40 | 0.04 | 0.00 |
| Other | `google.gemma-4-e2b` | 0.05 | 0.10 | 0.01 | 0.00 |

## Model aliases

Short aliases map to canonical model IDs for convenience.

```python
from shipit_agent.costs.pricing import MODEL_ALIASES

# Built-in aliases
# "opus"      -> "claude-opus-5-5"
# "sonnet"    -> "claude-sonnet-5-5"
# "haiku"     -> "claude-haiku-4"
# "gpt4o"     -> "gpt-5.5"
# "gpt4o-mini" -> "gpt-5.5"
```

Aliases are resolved automatically in `calculate_cost` and `record_call`.

```python
# These are equivalent
tracker.calculate_cost("opus", input_tokens=1000, output_tokens=500)
tracker.calculate_cost("claude-opus-5-5", input_tokens=1000, output_tokens=500)
```

## Calculating costs

Calculate cost without recording a call.

```python
cost = tracker.calculate_cost(
    model="claude-sonnet-5-5",
    input_tokens=10_000,
    output_tokens=2_000,
    cache_read_tokens=5_000,
    cache_write_tokens=1_000,
)
print(f"${cost:.6f}")
# input:       10,000 * $3.00  / 1M = $0.030000
# output:       2,000 * $15.00 / 1M = $0.030000
# cache_read:   5,000 * $0.30  / 1M = $0.001500
# cache_write:  1,000 * $3.75  / 1M = $0.003750
# total:                              $0.065250
```

If a model is not found in the pricing table, the cost returns `$0.00` and a warning is logged.

## Recording calls

`record_call` calculates cost, stores a `CostRecord`, updates the running total, and checks budget limits.

```python
record = tracker.record_call(
    model="claude-sonnet-5-5",
    input_tokens=8_000,
    output_tokens=1_500,
    cache_read_tokens=3_000,
    cache_write_tokens=500,
)

print(record.call_number)      # 1
print(record.model)            # "claude-sonnet-5-5"
print(f"${record.cost_usd:.6f}")  # cost for this call
print(record.timestamp)        # UTC datetime
```

### CostRecord fields

| Field | Type | Description |
|-------|------|-------------|
| `call_number` | `int` | Monotonically increasing call index (starts at 1) |
| `model` | `str` | Model identifier used for pricing |
| `input_tokens` | `int` | Prompt tokens |
| `output_tokens` | `int` | Completion tokens |
| `cache_read_tokens` | `int` | Tokens read from prompt cache |
| `cache_write_tokens` | `int` | Tokens written to prompt cache |
| `cost_usd` | `float` | Computed cost in USD |
| `timestamp` | `datetime` | UTC time of the call |

```python
# Serialize a record
d = record.to_dict()
```

## Budget enforcement

Set a hard spending limit. The tracker raises `BudgetExceededError` when the accumulated cost exceeds the budget, and emits a warning callback when crossing the warning threshold.

```python
from shipit_agent.costs import Budget, BudgetExceededError

budget = Budget(
    max_dollars=5.00,   # hard limit
    warn_at=0.80,       # warn at 80% ($4.00)
)

tracker = CostTracker(budget=budget)
```

### Budget fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_dollars` | `float` | required | Maximum spend allowed in USD |
| `warn_at` | `float` | `0.80` | Fraction (0.0--1.0) at which to emit a warning |

```python
budget.should_warn(4.10)   # True (4.10 >= 5.00 * 0.80)
budget.is_exceeded(5.01)   # True (5.01 > 5.00)
```

### Catching budget errors

```python
from shipit_agent.costs import BudgetExceededError

try:
    result = agent.run("Expensive analysis task")
except BudgetExceededError as e:
    print(f"Stopped: ${e.spent:.2f} spent of ${e.budget:.2f} limit (model: {e.model})")
```

`BudgetExceededError` attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `spent` | `float` | Total USD spent so far |
| `budget` | `float` | Configured budget limit |
| `model` | `str` | Model ID of the call that caused the breach |

## Warning callbacks

Get notified when the budget warning threshold is crossed (fires once per tracker lifecycle).

```python
def on_budget_warning(spent: float, limit: float) -> None:
    pct = (spent / limit) * 100
    print(f"WARNING: ${spent:.2f} of ${limit:.2f} ({pct:.0f}%)")
    # Send Slack alert, log to metrics, etc.

tracker = CostTracker(
    budget=Budget(max_dollars=10.00, warn_at=0.70),
    on_cost_alert=on_budget_warning,
)
```

## Cost breakdown and attribution

### Per-call breakdown

```python
for call in tracker.breakdown():
    print(f"Call #{call['call_number']} ({call['model']}): ${call['cost_usd']:.6f}")
    print(f"  in={call['input_tokens']} out={call['output_tokens']}")
    print(f"  cache_read={call['cache_read_tokens']} cache_write={call['cache_write_tokens']}")
```

### Full summary

```python
summary = tracker.summary()
print(f"Total cost: ${summary['total_cost_usd']:.4f}")
print(f"Total calls: {summary['total_calls']}")
print(f"Total tokens: {summary['total_tokens']}")

if "budget" in summary:
    b = summary["budget"]
    print(f"Budget: ${b['max_dollars']:.2f}")
    print(f"Remaining: ${b['remaining']:.2f}")
    print(f"Used: {b['percent_used']:.1f}%")
```

Summary structure:

```text
{
    "total_cost_usd": 1.234567,
    "total_calls": 5,
    "total_tokens": {
        "input_tokens": 50000,
        "output_tokens": 12000,
        "cache_read_tokens": 30000,
        "cache_write_tokens": 5000,
    },
    "calls": [
        {"call_number": 1, "model": "claude-sonnet-5-5", "cost_usd": 0.045, ...},
        ...
    ],
    "budget": {
        "max_dollars": 5.0,
        "warn_at": 0.8,
        "remaining": 3.765433,
        "percent_used": 24.69,
    },
}
```

## Token totals

Aggregate token counts across all recorded calls.

```python
totals = tracker.total_tokens
print(f"Input:       {totals['input_tokens']:,}")
print(f"Output:      {totals['output_tokens']:,}")
print(f"Cache read:  {totals['cache_read_tokens']:,}")
print(f"Cache write: {totals['cache_write_tokens']:,}")
```

## Custom model pricing

Register pricing for models not in the built-in table.

```python
tracker.add_model("my-custom-model", {
    "input": 1.50,     # $1.50 per million input tokens
    "output": 5.00,    # $5.00 per million output tokens
})

# Now track calls to your custom model
tracker.record_call(model="my-custom-model", input_tokens=10_000, output_tokens=2_000)
```

Override built-in pricing at construction time:

```python
tracker = CostTracker(
    pricing={
        "claude-sonnet-5-5": {
            "input": 2.50,   # your negotiated rate
            "output": 12.00,
        },
    },
)
```

The custom pricing dict is merged with `MODEL_PRICING` -- your entries override built-in entries with the same key.

## Auto-hooking with as_hooks()

`as_hooks()` creates `AgentHooks` that automatically extract token usage from LLM responses and record costs. It handles multiple response formats (Anthropic SDK, OpenAI SDK, shipit_agent `LLMResponse`).

```python
hooks = tracker.as_hooks()
agent = Agent.with_builtins(llm=llm, hooks=hooks)
```

What the hooks do:

| Hook | Action |
|------|--------|
| `on_before_llm` | Pre-call budget check -- raises `BudgetExceededError` early if already over limit |
| `on_after_llm` | Extracts usage from the response, calls `record_call`, checks budget again |

The model name is auto-detected from the response object. Override with an explicit name:

```python
hooks = tracker.as_hooks(model_name="claude-sonnet-5-5")
```

### Usage extraction patterns

The tracker tries multiple patterns to extract token counts from LLM responses:

1. `response.usage.input_tokens` / `response.usage.output_tokens` (Anthropic SDK)
2. `response.usage.prompt_tokens` / `response.usage.completion_tokens` (OpenAI SDK)
3. `response.metadata["usage"]` (dict-based wrappers)
4. `response.raw_response.usage` (shipit_agent `LLMResponse` wrapper)

Anthropic cache fields are extracted from `cache_read_input_tokens` and `cache_creation_input_tokens`.

## Cache savings (Anthropic prompt caching)

When using Anthropic models with prompt caching, cached tokens cost significantly less. The tracker tracks cache reads and writes separately so you can see exact savings.

```python
# After a run with caching enabled
summary = tracker.summary()
tokens = summary["total_tokens"]

regular_input_cost = tokens["input_tokens"] * 3.00 / 1_000_000  # sonnet input
cache_read_cost = tokens["cache_read_tokens"] * 0.30 / 1_000_000  # 10x cheaper
cache_write_cost = tokens["cache_write_tokens"] * 3.75 / 1_000_000

savings = (tokens["cache_read_tokens"] * (3.00 - 0.30)) / 1_000_000
print(f"Cache savings: ${savings:.4f}")
```

## Multi-model cost tracking

A single tracker handles calls across different models. The pricing table is consulted per-call.

```python
tracker = CostTracker(budget=Budget(max_dollars=20.00))

# Track calls to different models
tracker.record_call(model="claude-opus-5-5", input_tokens=5000, output_tokens=1000)
tracker.record_call(model="claude-sonnet-5-5", input_tokens=20000, output_tokens=5000)
tracker.record_call(model="gpt-5.5", input_tokens=15000, output_tokens=3000)

# Breakdown shows per-call model attribution
for call in tracker.breakdown():
    print(f"#{call['call_number']} {call['model']}: ${call['cost_usd']:.4f}")
```

## Streaming + live cost tracking

Track costs during streaming runs. Each LLM call in the agent loop triggers the `on_after_llm` hook, so costs accumulate in real time.

```python
tracker = CostTracker(budget=Budget(max_dollars=2.00))
agent = Agent.with_builtins(llm=llm, hooks=tracker.as_hooks())

for event in agent.stream("Analyze this repository"):
    if event.type == "run_completed":
        print(f"Final cost: ${tracker.total_cost:.4f}")
    elif event.type == "tool_completed":
        print(f"Running cost: ${tracker.total_cost:.4f}")
```

## Resetting the tracker

Clear all recorded calls and reset the total cost. Useful between runs or in test suites.

```python
tracker.reset()
print(tracker.total_cost)        # 0.0
print(len(tracker.breakdown()))  # 0
```

## Full production example

```python
import os
from shipit_agent import Agent
from shipit_agent.costs import CostTracker, Budget, BudgetExceededError

tracker = CostTracker(
    budget=Budget(max_dollars=5.00, warn_at=0.70),
    on_cost_alert=lambda spent, limit: print(
        f"ALERT: ${spent:.2f} of ${limit:.2f} ({spent/limit*100:.0f}%)"
    ),
)

agent = Agent.with_builtins(
    llm=llm,
    hooks=tracker.as_hooks(),
)

try:
    result = agent.run("Deep analysis of the authentication module")
except BudgetExceededError as e:
    print(f"Budget exceeded: ${e.spent:.2f} > ${e.budget:.2f}")

# Post-run analysis
summary = tracker.summary()
print(f"\nTotal: ${summary['total_cost_usd']:.4f}")
print(f"Calls: {summary['total_calls']}")

tokens = summary["total_tokens"]
print(f"Input tokens:  {tokens['input_tokens']:,}")
print(f"Output tokens: {tokens['output_tokens']:,}")
print(f"Cache reads:   {tokens['cache_read_tokens']:,}")
print(f"Cache writes:  {tokens['cache_write_tokens']:,}")

if "budget" in summary:
    print(f"Budget used:   {summary['budget']['percent_used']:.1f}%")
    print(f"Remaining:     ${summary['budget']['remaining']:.4f}")
```

## Using with plain Agent (no builtins)

```python
from shipit_agent import Agent

tracker = CostTracker(budget=Budget(max_dollars=1.00))

# Plain Agent — no built-in tools
agent = Agent(
    llm=llm,
    prompt="You explain concepts clearly.",
    hooks=tracker.as_hooks(),
)

result = agent.run("Explain the CAP theorem")
print(f"Cost: ${tracker.total_cost:.4f}")
```

## Using with DeepAgent

```python
from shipit_agent.deep import DeepAgent

tracker = CostTracker(budget=Budget(max_dollars=5.00, warn_at=0.80))

deep = DeepAgent.with_builtins(
    llm=llm,
    verify=True,
    reflect=True,
    hooks=tracker.as_hooks(),
)

result = deep.run("Research and summarize AI agent architectures")
print(f"DeepAgent cost: ${tracker.total_cost:.4f}")
print(f"Calls: {len(tracker.breakdown())}")
```

## Using with ShipCrew

```python
from shipit_agent.deep.ship_crew import ShipCrew, ShipAgent, ShipTask

tracker = CostTracker(budget=Budget(max_dollars=3.00))

# All crew agents share the same tracker
crew = ShipCrew(
    name="tracked-crew",
    coordinator_llm=llm,
    agents=[
        ShipAgent(name="r", agent=Agent(llm=llm, prompt="Research.", hooks=tracker.as_hooks()), role="Researcher"),
        ShipAgent(name="w", agent=Agent(llm=llm, prompt="Write.", hooks=tracker.as_hooks()), role="Writer"),
    ],
    tasks=[
        ShipTask(name="research", description="Research {topic}", agent="r", output_key="findings"),
        ShipTask(name="write", description="Summarize: {findings}", agent="w", depends_on=["research"]),
    ],
)

result = crew.run(topic="edge computing")
print(f"Crew total cost: ${tracker.total_cost:.4f}")
for c in tracker.breakdown():
    print(f"  #{c['call_number']}: ${c['cost_usd']:.4f}")
```

## Streaming with live cost display

```python
tracker = CostTracker(budget=Budget(max_dollars=2.00))

agent = Agent.with_builtins(
    llm=llm,
    prompt="You are a helpful analyst.",
    hooks=tracker.as_hooks(),
)

for event in agent.stream("List 5 metrics for evaluating AI agents"):
    if event.type == "run_started":
        print(f"🚀 Started | Cost: ${tracker.total_cost:.4f}")
    elif event.type == "tool_called":
        print(f"🔧 Tool called | Cost: ${tracker.total_cost:.4f}")
    elif event.type == "run_completed":
        print(f"🏁 Done | Final cost: ${tracker.total_cost:.4f}")
        print(f"   Tokens: {tracker.total_tokens}")
        print(event.payload.get("output", "")[:300])
```

## API reference

| Class / Method | Description |
|----------------|-------------|
| `CostTracker(budget, pricing, on_cost_alert)` | Create a tracker with optional budget and custom pricing |
| `tracker.total_cost` | Total accumulated cost in USD (property) |
| `tracker.total_tokens` | Aggregate token counts as a dict (property) |
| `tracker.calculate_cost(model, input_tokens, output_tokens, ...)` | Calculate cost without recording |
| `tracker.record_call(model, input_tokens, output_tokens, ...)` | Record a call, return `CostRecord`, check budget |
| `tracker.breakdown()` | Per-call cost attribution as list of dicts |
| `tracker.summary()` | Full summary with totals, calls, and budget status |
| `tracker.add_model(model_id, pricing)` | Register custom model pricing |
| `tracker.check_budget()` | Manually check if budget is exceeded |
| `tracker.reset()` | Clear all calls and reset total cost |
| `tracker.as_hooks(model_name)` | Create `AgentHooks` for automatic tracking |
| `Budget(max_dollars, warn_at)` | Budget configuration dataclass |
| `budget.should_warn(spent)` | Check if warning threshold is crossed |
| `budget.is_exceeded(spent)` | Check if budget limit is exceeded |
| `BudgetExceededError` | Exception with `.spent`, `.budget`, `.model` attributes |
| `CostRecord` | Dataclass for a single call's cost breakdown |
| `record.to_dict()` | Serialize a cost record |
| `MODEL_PRICING` | Built-in per-million-token pricing table |
| `MODEL_ALIASES` | Short name to canonical model ID mapping |
