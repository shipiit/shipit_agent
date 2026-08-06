# What we took from Cloudflare OS, and what is still open

A tool-by-tool audit against the reference implementation
(`others/_reference_cloudflare_os`), so "what's left?" has an answer that
someone can check rather than trust.

Their agent has **15 tools**. Ours now covers 13 of them, one deliberately
differently, and one not at all.

## Their tool set, and where it lands here

| Cloudflare OS | shipit_agent | Notes |
|---|---|---|
| `readFile` | `read_file` | ✅ |
| `writeFile` | `write_file` | ✅ + revert, contracts, approvals |
| `editFile` | `edit_file` | ✅ |
| `describeBinding` | `describe_binding` | ✅ progressive disclosure, same idea |
| `executeCode` | `execute_code` | ✅ over the capability bridge |
| `giveUp` | `give_up` | ✅ a declared stop, not inferred from prose |
| `webFetch` | `open_url` | ✅ (plus `web_search`, `deep_research`) |
| `listConnectableResources` | `connections` | ✅ five states, incl. `EXPIRED` |
| `requestConnection` | `connections` + approvals | ✅ the card is an `ApprovalRow` |
| `listBlueprints` | `list_blueprints` | ✅ three shipped blueprints |
| `createGadget` | `create_app` | ✅ see `shipit_agent/apps.py` |
| `setGadgetBinding` | `set_app_binding` | ✅ an app sees only what it was wired |
| `saveCapsuleAsBinding` | — | ⛔ obsolete in their own codebase |
| `setBindingHook` | — | ❌ **open** — resource-triggered runs |
| `observeUserChanges` | — | ⛔ n/a: needs a live shared document |

Two of ours have no counterpart there, because their model does not have the
problem: `sub_agent` (their context strategy is compaction, ours is
delegation) and `ask_user` (their approval cards cover it).

## Still open

**`setBindingHook` — resource-triggered runs.** Theirs wires a resource to an
entrypoint so that *the resource* starts the agent: an email arrives, the
workflow runs. Ours has `agent.stream()` and nothing that listens. This is the
"runs on every email" label in their UI, and it is the single largest
remaining gap — it turns an agent you ask into an agent that reacts.

What it needs here: a trigger registry (resource → entrypoint), a way to run
an agent headless on an event, and a durable queue so a trigger that fires
while nothing is listening is not lost.

**`observeUserChanges`** is not a gap to close. It exists because their
workspace is a live document several people edit at once; the agent needs to
know what changed under it. There is no shared document here.

## What was adapted rather than copied

- **Gadgets → apps.** Theirs are Workers on Durable Objects, deployed and
  shared and rendered in a sidebar. Ours are directories that run in a
  subprocess. The *idea* — build once, wire resources explicitly, run again
  later, and say `Used the app` in the transcript — is what carried over.
- **Simulated action results.** When they defer an action, the model is told
  what the result *would have been*. We tell it the truth: queued, not run,
  do not read back its effects. Fabricating results to keep a turn flowing is
  a bad trade in a runtime people will point at production systems.
- **The canvas.** Their right-hand pane (a spreadsheet, a workflow diagram,
  presence avatars) is a hosted web product: Durable Objects for the shared
  state, a CRDT for concurrent edits, WebSockets for presence. A Python
  runtime rendering into a notebook cell does not get there, and pretending
  otherwise would be a demo rather than a feature. What did carry over is the
  left rail: the transcript, tool rows with real output, approval cards, the
  tokens footer — see `shipit_agent/narrate/live_ui.py`.

## Beyond their set

Things here with no Cloudflare OS counterpart, listed so the comparison is
honest in both directions: automatic delegation (`shipit_agent/delegation.py`),
the tree view, the UI timeline, MCP servers as first-class tool sources,
sub-agent specialists, guardrails, the verifier network, RAG, cost tracking
and budgets, and 50-odd integration tools that their design deliberately
replaces with bindings.
