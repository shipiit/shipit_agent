# SHIPIT Agent v1.0.6 — Announcement Kit

Copy-paste-ready posts for Twitter/X, LinkedIn, and Peerlist.

---

## Twitter / X Thread

### Tweet 1 (Main)

```
shipit-agent v1.0.6 is out 🚀

Autopilot is now bulletproof for 24-hour runs. New render_dashboard tool lets the agent build HTML one-pagers from any question. LiteLLM proxy: plug your own URL + key and every agent uses it.

pip install shipit-agent==1.0.6

🧵 What's new ↓
```

### Tweet 2 — Bulletproof 24h

```
Autopilot survives multi-day runs now.

• Cumulative budgets across resume — crash at hour 12, resume for 12 more, 24h cap fires at hour 24 (not 36).
• SIGTERM-safe — systemd stop halts cleanly + saves one final checkpoint.
• Corrupt checkpoints are quarantined, not silently dropped.
• Dollars actually track end-to-end.
```

### Tweet 3 — Dashboards, the agent picks the shape

```
New tool: render_dashboard.

The agent picks the section types (metrics, chart, timeline, cards, phases, verdict) for the question. Output is a single self-contained HTML file.

agent.run("Give me a Q2 sales dashboard for the board.")
→ life_vision.html, finance.html, market-entry.html…
```

### Tweet 4 — Bring your own LiteLLM

```
Bring your own LiteLLM proxy with THREE fields.

llm = build_llm_from_settings({
  "provider": "litellm",
  "model":    "gpt-4o-mini",
  "api_base": "https://litellm.acme.com",
  "api_key":  "sk-proxy-...",
}, provider="litellm")

Agent, Autopilot, ShipCrew all use it. Cost tracking / rate limits live on your proxy.
```

### Tweet 5 — Bedrock works on more models

```
Bedrock adapter now works on the full model catalog.

Previously it sent an Anthropic-only param that Nova / Titan / Llama / Mistral rejected with "extraneous key [modify_params]". Now it's gated on the model.

Claude on Bedrock, Nova, gpt-oss-120b — all just work.
```

### Tweet 6 — The proof

```
904 unit tests.
7 opt-in Bedrock end-to-end tests.
1 opt-in soak (run it for any duration).
All passing.

Also new: Python 3.13 + 3.14 support in the matrix.

Docs: https://docs.shipiit.com/
Changelog: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.6
```

---

## LinkedIn

```
SHIPIT Agent v1.0.6 — Bulletproof 24h Autopilot, AI-driven Dashboards, LiteLLM proxy

Just shipped a big update to shipit-agent, our open-source Python agent framework.

The theme: production-grade long-running agents.

OpenAI's new agents released recently — the ones that can work for hours. Ours now matches that class of workload, but in a library you can pip install.

→ Autopilot is bulletproof for 24-hour runs. Cumulative budgets across resume (crash at hour 12, resume for another 12 hours, the 24-hour cap still fires exactly at hour 24 — not hour 36). SIGTERM and SIGHUP are caught alongside SIGINT so systemd/launchd stops halt cleanly with one final checkpoint. Dollar tracking is wired end-to-end via the pricing table, so max_dollars actually fires instead of always reading $0. Corrupt checkpoints are quarantined to <run_id>.corrupted.<ts>.json so operators can inspect what went wrong instead of silently losing state. First-iteration heartbeat + a "remaining" budget payload on every event for live ETA bars.

→ render_dashboard — a tool where the agent picks the shape. Hand it to any Agent and ask "give me a Q2 sales dashboard for the board" or "product-launch readiness one-pager" or "market-entry brief for Vietnam." The model decides which sections fit (metrics tiles, line chart, bars, timeline, comparison cards, phase stack, verdict box), builds the spec, and the tool emits a single self-contained HTML document. Inline CSS. Chart.js via CDN only when needed. User strings escaped. Colors pass through a hex allow-list. Drops into Autopilot's artifact collector with zero glue code.

→ Bring your own LiteLLM proxy — three fields. Companies running a self-hosted LiteLLM proxy (litellm --config) point every Agent, Autopilot, and ShipCrew at it with model, api_base, api_key. The proxy handles upstream credentials, rate-limiting, routing, cost tracking. shipit-agent speaks OpenAI-compatible HTTP to it. Three equivalent paths: factory, direct class, or pure env vars.

→ Bedrock adapter now works across the full model catalog. Previously BedrockChatLLM injected modify_params=True unconditionally (an Anthropic-only workaround), which Nova, Titan, Llama, Mistral, and openai.gpt-oss-120b on Bedrock rejected. Now it's gated on the model family — Claude on Bedrock works, and so does everything else.

→ Python 3.13 + 3.14 support added to classifiers and the CI matrix.

The proof: 904 unit tests, 7 opt-in end-to-end tests against a real AWS Bedrock model, and a 1 opt-in soak test (gated on SHIPIT_AUTOPILOT_SOAK=<seconds>) that drives a real Bedrock Autopilot for whatever duration you give it. All passing.

pip install shipit-agent==1.0.6
Docs: https://docs.shipiit.com/
GitHub: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.6

#opensource #python #ai #agents #llm #bedrock #litellm #developer #shipitagent
```

---

## Peerlist

### Project update title

```
shipit-agent 1.0.6 — 24h Autopilot, AI dashboards, LiteLLM proxy
```

### Short summary (for the card)

```
Bulletproof 24-hour Autopilot (cumulative budgets across resume · SIGTERM-safe · dollar tracking · corrupt-checkpoint quarantine), a new render_dashboard tool the agent drives to produce Claude-Desktop-style HTML one-pagers, and first-class LiteLLM proxy support — plug every agent into your own proxy in three fields. 904 tests pass.
```

### Long description

```
SHIPIT Agent is an open-source Python agent framework — bring your own LLM, attach tools, MCP servers, and third-party connectors (Gmail, Drive, Slack, Linear, Jira, Notion, Confluence). The runtime is small enough to read in an afternoon and explicit enough to extend without fighting it.

1.0.6 is the "production long-running agents" release.

🛡 Autopilot is bulletproof for 24-hour runs.
• Cumulative budgets across resume — every field of BudgetUsage (seconds, tool calls, tokens, dollars, iterations) persists in the checkpoint. A run that crashes at hour 12 and resumes for another 12 hours trips a 24-hour cap exactly at hour 24, not hour 36.
• SIGTERM / SIGHUP caught alongside SIGINT so systemd stop / launchd stop halt cleanly with one final checkpoint. Autopilot.request_stop(reason) is a thread-safe external halt for daemons and UIs.
• Dollar tracking is wired end-to-end via the pricing table, so max_dollars budgets actually fire instead of always reading $0.
• Corrupt checkpoints are quarantined as <run_id>.corrupted.<timestamp>.json instead of silently dropped — operators can inspect what went wrong.
• First-iteration heartbeat + a "remaining" per-axis payload on every iteration / heartbeat event so UIs can render live ETA bars.

🎨 render_dashboard — a tool where the agent picks the shape.
Hand the tool to any Agent and ask for a dashboard. The model decides which sections fit (metrics, line_chart, bar_chart, bars, timeline, cards, lifestyle_grid, phases, callout, verdict) for the question being asked. Output is a single self-contained HTML document — inline CSS, Chart.js via CDN only when a chart section is present, all user strings HTML-escaped, colors filtered through a hex allow-list. Drops into Autopilot's artifact collector with zero glue code.

Same agent, different dashboards:
• "Q2 sales dashboard for the board"
• "Product-launch readiness one-pager"
• "10-year town climate summary"
• "Market-entry brief for Vietnam"

🔌 Bring your own LiteLLM proxy.
Three fields (model, api_base, api_key) plug every Agent, Autopilot, and ShipCrew into a self-hosted LiteLLM proxy. The proxy handles upstream credentials, rate-limiting, routing, cost tracking; shipit-agent speaks OpenAI-compatible HTTP to it. Three equivalent wiring paths: factory (build_llm_from_settings), direct class (LiteLLMProxyChatLLM), or pure env vars (SHIPIT_LITELLM_API_BASE triggers proxy mode automatically).

🔧 Extra fixes.
• BedrockChatLLM works across the full Bedrock model catalog — Claude, Nova, Titan, Llama, Mistral, openai.gpt-oss-120b. Previously only Claude worked.
• AgentRegistry.all() alias for list_all().
• Python 3.13 + 3.14 added to classifiers and CI matrix.

📓 Notebook 46 shows it all end-to-end.
Pick an LLM (Bedrock / LiteLLM direct / LiteLLM proxy) → render_dashboard → Agent with the tool → Autopilot artifact ingest. Executes clean, produces two HTML dashboards under notebooks/_dashboard_workspace/.

✅ 904 unit tests + 7 opt-in Bedrock end-to-end + 1 opt-in soak. All passing.

Install: pip install shipit-agent==1.0.6
Docs:    https://docs.shipiit.com/
GitHub:  https://github.com/shipiit/shipit_agent/releases/tag/v1.0.6
```

### Tags / hashtags

```
python, ai, agents, llm, opensource, bedrock, litellm, autopilot, developer-tools, dashboards
```

---

## Cross-post checklist

- [ ] Twitter/X thread (6 tweets above)
- [ ] LinkedIn long-form post
- [ ] Peerlist project update
- [ ] Pin the Twitter thread on the shipit-agent profile
- [ ] Reply to the Twitter thread with the GitHub release URL once analytics are flowing
- [ ] Update LinkedIn company page "Featured" section with the 1.0.6 post
- [ ] Post a short note in any community channels you're in (Slack, Discord) linking to the LinkedIn + Twitter

---

## Links to include

- PyPI: https://pypi.org/project/shipit-agent/1.0.6/
- GitHub release: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.6
- Docs — Autopilot: https://docs.shipiit.com/autopilot/
- Docs — render_dashboard: https://docs.shipiit.com/tools/dashboard-render/
- Docs — LiteLLM proxy: https://docs.shipiit.com/guides/litellm-proxy/
- Notebook 46: https://github.com/shipiit/shipit_agent/blob/main/notebooks/46_dashboard_render_tool_and_litellm.ipynb
