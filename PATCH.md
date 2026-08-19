# PATCH — wiring the new machinery into your `agent.py`

Your `Agent` keeps all 57 fields and all 20 methods. The change is two lines.

## The patch

```diff
--- a/shipit_agent/agent.py
+++ b/shipit_agent/agent.py
@@
 from shipit_agent.skills import (
     ...
 )
+from shipit_agent.agent_mixin import UpgradeMixin

@@
 @dataclass
-class Agent:
+class Agent(UpgradeMixin):
     """The primary SHIPIT agent — LLM + tools + skills + RAG in one class."""
```

That is the whole integration. `run`, `stream`, `run_live`, `stream_sse`,
`plan`, `narrate`, `doctor`, `clone`, `as_tool`, `with_builtins`, `for_project`,
`for_role`, `chat_session`, `reason` — untouched. A test asserts the mixin adds
no name that already exists on `Agent`, so nothing can be shadowed by accident.

Rolling back is deleting the two lines.

## What it gives you

```python
agent = Agent(llm=llm, tools=[...], mcps=[...], skills=[...])

agent.preflight()          # what would go wrong, before spending a token
agent.upgrade_report()     # configured features the new loop does not cover
agent.describe_tools_v2()  # every reachable tool: bound now, or behind search
agent.describe_model_v2()  # the resolved capability row

agent.run_v2("Fix the failing tests")
for event in agent.stream_v2("..."):   # live tool output, skill loads, sub-agents
    render(event)
for packet in agent.packets_v2("..."): # typed, for a UI or SSE endpoint
    render(packet)
```

Both loops read the same configuration — `bridge.spec_from_agent` maps your
fields, none renamed — so you can compare them on real work instead of arguing
about them. `run` stays until `run_v2` is demonstrably better on your workload.

## Start with preflight

It costs no model call and reports most misconfiguration:

```python
>>> agent.preflight()
{
  'model': 'google.gemma-4-31b',
  'schema_dialect': 'openai_strict',
  'context_window': 256000,
  'prefix_tokens': 4820,
  'prefix_share': 0.02,
  'tools_bound': 9,
  'tools_deferred': 41,
  'skills': 7,
  'parameters': 'sent: temperature, top_p; used locally: max_context_tokens; '
                'blocked for this model: top_k, frequency_penalty',
  'mcp': {'servers': 5, 'healthy': 4, 'failed': {'slack': 'token expired'}},
  'warnings': [
      'MCP server slack unavailable: token expired',
      'Blocked for this model and not sent: frequency_penalty, top_k',
  ],
  'not_yet_in_v2': ['code_mode', 'rag'],
}
```

Four things visible there that were previously only findable mid-run: a dead
connector, two parameters this model rejects, the real prefix cost, and which of
your configured features `run_v2` does not yet reproduce.

## What each part now does for you

**Providers.** `llms/capabilities.py` carries context windows as data, so Gemma
compacts at 256K rather than a table default. `llms/parameters.py` splits wire
params from host params — `max_context_tokens` is an instruction to your
compactor, and forwarding it to Mantle is a 400 on a field you never aimed at the
provider. `llms/schema_prep.py` inlines `$ref`, which your tree had nowhere and
which every Pydantic-based MCP server emits.

**Tools.** Twelve packages under `tools/`, one capability each, prompt text next
to the tool it describes. Contracts enforced rather than suggested: `write_file`
refuses to clobber, `edit_file` refuses an unread file or an ambiguous match.

**MCP.** `mcp_bridge.py` describes servers from cache, defers the expensive tail
behind `tool_search`, and connects only when a tool is actually called. It also
injects each server's `instructions` — the field your `mcp.py:646` reads and
never uses.

**Connections.** `connections/mcp.py` sits beside your `models.py` and
`registry.py`. Yours answers "has the user connected Jira?"; this answers "how do
I start Jira's server?". Both are needed; neither replaces the other.

**Skills.** Catalog in the cached prefix, bodies loaded on demand at any
iteration. Your seven skills cost 1,063 characters of catalog against 16,875
characters of body.

**Prefix.** `prefix.py` + `prefix_rules.py` keep the prompt head byte-stable, so
implicit caching on Mantle actually hits. Your `rules/` is rendered into it —
scoped by active tools, ordered deterministically — which nothing was doing.

## Then, in order

1. **`models.py`** — merge it. Superset of yours; grep for
   `metadata["tool_call_id"]` and switch those reads to the fields. This is what
   lets you drop `modify_params=True`.
2. **`llms/schema_prep.py`** — three lines in each adapter. Highest chance of
   being the live Gemma bug.
3. **The two-line patch above.** Run `preflight()` on your real agents.
4. **Compare `run` against `run_v2`** on a task you care about.
5. **Close the gaps `upgrade_report()` names** before switching anything over —
   `hooks`, `plugins`, `guardrails`, `verifier`, `rag` and
   `parallel_tool_execution` are the ones that would change behaviour if lost.
