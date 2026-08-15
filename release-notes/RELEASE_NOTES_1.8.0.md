# shipit-agent 1.8.0 — The platform

A strong runtime knows how to run. A platform lets you **add to it without
opening it.** This release turns three of the agent's biggest surfaces —
connections, model providers, and (next) tools — into clean drop-in
directories: one unit per folder, a declarative manifest, a loader that
validates and skips-the-broken. Adding a connector or a provider becomes a
data edit, not a pull request.

```python
from shipit_agent import Agent, connect, list_connectors
from shipit_agent.providers import list_providers

# Every integration is one line — 28 ship in the catalog:
linear = connect("linear", token=user_token)      # hosted, per-user OAuth
slack  = connect("slack")                          # local stdio server

# Every model provider is a profile you can list, pick, and build:
for p in list_providers():
    print(p.name, p.display_name, "· vision" if p.supports_vision else "")

agent = Agent(llm=llm, mcps=[linear, slack], deferred_tools=True)
agent.run("What Linear issues are assigned to me this cycle?")
```

## Connections as data — 28 connectors, self-refreshing OAuth

Every integration is an MCP server described by one declarative
`manifest.yaml` under `connectors/catalog/<name>/`. The registry scans them,
validates each, and **skips an invalid one with a diagnostic** — a typo in a
single manifest never brings down the catalog. `connect(name)` turns a manifest
into a live MCP server, choosing the hosted (HTTP/SSE) or stdio transport and
wiring the per-user bearer token.

The catalog ships **28 connectors** across six categories — GitHub, GitLab,
Linear, Jira, Confluence, Sentry, Slack, Discord, Intercom, Notion, Asana,
ClickUp, Todoist, Google Drive, Postgres, SQLite, Brave Search, Fetch, Google
Maps, Airtable, Stripe, PayPal, Square, Filesystem, Playwright, Puppeteer,
Memory, Cloudflare.

The classic reason connections "work, then stop" is an access token expiring
with nothing to refresh it. `OAuthCredentialManager` resolves the right user's
token at call time and **refreshes it transparently** near expiry, recovers
from a live 401 with one refresh, dedupes concurrent refreshes, and reports
`connected` / `expired` / `disconnected` for a dashboard. **38 provider presets**
carry the authorize/token/refresh endpoints, so a connector's OAuth is one
`register_preset(...)`. Tokens live behind a small `TokenStore` protocol —
in-memory, `0600` file-backed, or your own database adapter.

## Every model, one profile

The factory's per-provider `if/elif` chain is now a **provider catalog**. Each
provider is `providers/catalog/<name>/profile.yaml` — display name, auth env,
adapter class, default model, capabilities (vision, prompt-cache,
fixed-temperature), fallback models — plus an optional `provider.py` for the
few that need imperative setup (Bedrock's region discovery, Anthropic's
package-missing fallback, Vertex's credential resolution).

Ten providers ship as profiles: **openai, anthropic, bedrock, gemini, vertex,
litellm, groq, together, ollama**, and the built-in **shipit/echo**. This layer
sits *on top of* the existing adapters — it does not rewrite them — so
`build_llm_from_settings` keeps its exact signature, defaults, and aliases, and
a new provider becomes a dropped-in directory.

## Only the tools the turn needs

With a big toolbelt — 60 builtins, 20 connectors, 150+ tools — sending every
schema on every request drowns the model and burns tokens on a question that
touches none of them. Pair the catalog with `deferred_tools=True` and the agent
keeps a small core resident and lists everything else by name until it reaches
for one.

Measured live on real providers with **61 tools held**:

| Provider | `deferred_tools=True` | eager | Saved |
| --- | --- | --- | --- |
| Bedrock gpt-oss-120b | 27,437 prompt tokens | 92,847 | **70% less** |
| Vertex Gemini 2.5 Flash | 27,133 (+8,571 cached) | 67,404 | **60% less** |

## Validated live

End-to-end agent runs — tools, `deferred_tools`, and a live MCP server —
against **Amazon Bedrock (gpt-oss-120b)**, **Vertex AI (Gemini 2.5 Flash &
Pro)**, and **LiteLLM routed to Bedrock**: reasoning events streaming
(`reasoning_started` / `reasoning_completed`), prompt caching active, tools
executing, and the token savings above.

## Compatibility

Fully backward-compatible. `build_llm_from_settings` behaves identically with or
without the catalog (it falls back to the inline chain when PyYAML isn't
installed), and every existing provider returns the same adapter class and
default model as before. The connector catalog and `pyyaml` live in the
`[connectors]` extra.
