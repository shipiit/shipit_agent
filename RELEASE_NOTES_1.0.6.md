# SHIPIT Agent 1.0.6

**Release date — 2026-04-24**

Bulletproof 24-hour Autopilot, an AI-driven dashboard renderer, and
first-class LiteLLM-proxy support. **904 unit tests. 7 opt-in Bedrock
end-to-end tests. 1 opt-in soak. All passing.**

---

## 1. Autopilot is now bulletproof for 24-hour runs

`Autopilot` has been the long-running, goal-driven runtime since 1.0.5.
In 1.0.6 we hardened every interface that a 24-hour job hits: cumulative
budgets across resume, signal-safe shutdown, dollar tracking that
actually works, and corrupt-checkpoint forensics.

```python
from shipit_agent import Autopilot, BudgetPolicy, Goal

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Audit every PR merged in the last 24 hours for security regressions",
        success_criteria=["No high-severity finding", "Report under 2 pages"],
    ),
    budget=BudgetPolicy(max_seconds=24 * 3600, max_dollars=5.0),
    artifacts=True,
)
# Crash at hour 12? systemd stop? VM reboot?
# Just `autopilot.resume(run_id)` — the 24-hour cap still fires at hour 24.
```

What changed under the hood:

- **Cumulative budgets across resume.** Every field of `BudgetUsage`
  (seconds, tool calls, tokens, dollars, iterations) persists in the
  checkpoint. A crash at hour 12 → resume for another 12 trips a
  24-hour cap exactly at hour 24, not hour 36.
- **Dollar tracking wired end-to-end.** `usage.dollars` accumulates from
  LLM response metadata via the pricing table, with Bedrock / LiteLLM
  prefix handling. `max_dollars` fires instead of always reading `$0`.
- **Signal-safe shutdown.** `SIGTERM` and `SIGHUP` are caught alongside
  `SIGINT` — `systemd stop` / `launchd stop` halt cleanly with one
  final checkpoint. `autopilot.request_stop(reason)` is a thread-safe
  external halt for daemons and UIs.
- **Corrupt-checkpoint quarantine.** A JSON parse error during `load()`
  moves the bad file to `<run_id>.corrupted.<ts>.json` instead of
  silently dropping it, so operators can inspect what went wrong.
- **First-iteration heartbeat + `remaining` payload on every event.**
  Slow first steps never look like hangs; UIs render live ETA bars.

Test coverage for these scenarios:

- `tests/test_autopilot_hardening.py` — 14 unit tests.
- `tests/test_autopilot_long_task.py` — 6 compressed-time simulations
  (many iterations, 5-crash resume chain, SIGTERM mid-run, mid-run
  corruption recovery, 50-child fan-out) + 1 opt-in Bedrock soak
  gated on `SHIPIT_AUTOPILOT_SOAK=<seconds>`.

---

## 2. `render_dashboard` — the agent picks the shape

Hand `DashboardRenderTool` to any `Agent` and ask for a dashboard. The
**model** decides which section types fit the question; you don't
hand-author the spec.

```python
from shipit_agent import Agent
from shipit_agent.tools.dashboard_render import DashboardRenderTool

agent = Agent(
    llm=llm,
    tools=[DashboardRenderTool()],
    prompt=(
        "You are a visual reporting assistant. When the user asks for a "
        "dashboard, one-pager, or visual summary, call render_dashboard "
        "with the section types that fit the question."
    ),
)

agent.run("Make a Q2-FY26 sales dashboard — KPIs, growth chart, top customers, risk callouts.")
agent.run("Product-launch readiness one-pager: checklist, owner cards, go/no-go verdict.")
agent.run("10-year climate summary for the town: temperature line, rainfall bars, drought timeline.")
agent.run("Market-entry brief for Vietnam: market metrics, competition cards, 4-phase plan.")
```

Section types the model can pick from: `metrics`, `line_chart` /
`bar_chart`, `bars`, `timeline`, `cards`, `lifestyle_grid`, `phases`,
`callout`, `verdict`. Output is a **single self-contained HTML
document** — inline CSS, Chart.js via CDN only when a chart section is
present, user strings escaped, colors pass through a hex allow-list
(no CSS injection).

Tool output shape matches `ArtifactCollector.ingest_tool_metadata`, so
a wrapping `Autopilot(..., artifacts=True)` captures the HTML as a
collected artifact with zero glue code.

Also exposed as a pure-Python function (`render_dashboard(spec)`) for
callers that already have the numbers.

See:

- Docs — [tools/dashboard-render](https://docs.shipiit.com/tools/dashboard-render/).
- Notebook — [`46_dashboard_render_tool_and_litellm.ipynb`](notebooks/46_dashboard_render_tool_and_litellm.ipynb).
- Tests — `tests/test_dashboard_render.py` (20 tests).

---

## 3. LiteLLM proxy — bring your own URL + key

Companies running a self-hosted LiteLLM proxy (`litellm --config`) can
now point every `Agent`, `Autopilot`, and `ShipCrew` at it in three
fields. The proxy handles upstream credentials, rate-limiting, routing,
cost tracking; shipit-agent speaks OpenAI-compatible HTTP to it.

```python
from shipit_agent.llms import build_llm_from_settings

llm = build_llm_from_settings({
    "provider": "litellm",
    "model": "gpt-4o-mini",
    "api_base": "https://litellm.my-company.internal",
    "api_key": "sk-proxy-abc123...",
}, provider="litellm")
```

Or imperatively via `LiteLLMProxyChatLLM(model=..., api_base=..., api_key=...)`,
or purely through environment variables (`SHIPIT_LITELLM_API_BASE`
triggers proxy mode automatically).

See — [guides/litellm-proxy](https://docs.shipiit.com/guides/litellm-proxy/)
for the full matrix (factory path, direct class, env-var path) and
error-retry behaviour.

---

## 4. Extra fixes

- `BedrockChatLLM` now only injects `modify_params=True` for Anthropic
  models on Bedrock. Nova, Titan, Llama, Mistral, and
  `openai.gpt-oss-120b` on Bedrock work without the previous
  "extraneous key [modify_params]" rejection.
- `AgentRegistry.all()` — convenience alias for `list_all()` so the
  common `.all()` idiom works.
- Notebook 44 + 45 regenerated against the current API
  (`AgentRegistry.default()`, `AgentDefinition.max_iterations`).

---

## How to run the verification yourself

```bash
# Fast — stubs only, ~10 seconds.
pytest

# Real Bedrock E2E (7 tests, ~10 seconds with a warm region).
SHIPIT_BEDROCK_E2E=1 \
SHIPIT_BEDROCK_E2E_MODEL=bedrock/openai.gpt-oss-120b-1:0 \
  pytest tests/test_autopilot_bedrock_e2e.py

# Soak a real Bedrock Autopilot for N seconds.
SHIPIT_AUTOPILOT_SOAK=300 \
  pytest tests/test_autopilot_long_task.py::test_bedrock_soak_for_requested_duration
```

---

## Upgrade

```bash
pip install --upgrade shipit-agent==1.0.6
```

No breaking changes. Existing checkpoints written by 1.0.5 load
transparently — the checkpoint store handles both schema v1
(iterations only) and v2 (full `BudgetUsage`).
