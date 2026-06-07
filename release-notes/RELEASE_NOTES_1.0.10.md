# shipit-agent 1.0.10 — Bug-fix & hardening release

**1.0.10 makes 1.0.x solid.** It fixes a v1.0.9 regression that broke custom
LLM adapters, closes a cluster of tool-security bypasses, and tightens
session, cost, and concurrency correctness — backed by 180+ new tests.

> No public API was removed. No caller needs code changes. Upgrade with
> `pip install -U shipit-agent`.

**1742 tests passing (+180 new) · 0 regressions · ruff clean.**

---

## 🔴 Critical fixes

### `text_delta_callback` regression (introduced in v1.0.9)
v1.0.9 added inline token streaming by passing a new `text_delta_callback`
argument to `LLM.complete()` — but the runtime passed it **unconditionally**.
Any adapter written against the previous protocol signature (every custom
adapter, and every test mock) raised
`TypeError: complete() got an unexpected keyword argument 'text_delta_callback'`
on the very first call.

The runtime now inspects the adapter's signature once and only passes the
callback to adapters that accept it. Old adapters work unchanged; streaming
still works for adapters that opt in.

### Multi-turn sessions stacked duplicate system prompts
Re-running an agent with a persistent `session_store` and a reused
`session_id` — the path `AgentChatSession` drives — re-appended a fresh system
message on every turn. Conversations grew without bound and ended up with
system messages buried mid-history (which several providers reject). The
runtime now injects exactly one leading system message and strips persisted
ones when it reloads a session.

---

## 🔒 Security hardening (tools)

| Tool | Fix |
| --- | --- |
| **Bash** | Rejects command substitution (`$(…)`, backticks), process substitution, and file redirection that could smuggle past the command allowlist. |
| **`open_url` / browser** | http(s)-only; blocks `file://` and private, loopback, link-local, and cloud-metadata IPs (SSRF). Opt out with `allow_private_hosts=True`. |
| **SQL** | Read-only guard scans the entire statement (not the first 500 chars) and rejects stacked statements — closes an `allow_writes=False` bypass on multi-statement drivers. |
| **OAuth** | `exchange_code(state=…)` validates and consumes the CSRF state nonce. |
| **`edit_file`** | Refuses to edit non-UTF-8 files instead of silently corrupting them. |
| **`FileCredentialStore`** | Warns that secrets are stored in plaintext, chmods the file `0600`, writes atomically. |

---

## ⚙️ Reliability & correctness

- **MCP**: transports are closed even when a run raises (`try/finally`), and a
  failed `discover_tools` handshake closes its transport — no leaked
  subprocesses.
- **Parallel tools**: each concurrent tool gets an isolated copy of shared
  state, merged deterministically — fixes a read-modify-write race.
- **Cost accounting**: the iteration-cap summary turn now counts its tokens and
  fires the after-LLM hook; `CostTracker` flags `has_unknown_pricing` and warns
  instead of silently billing unknown models at `$0` under a budget.
- **Parsing**: `JSONParser` extracts the balanced JSON object via a depth scan
  and prefers a ` ```json ` fence.
- **Pipelines**: `stream()` no longer executes agent steps twice.
- **Autopilot**: fan-out preserves input order (was sorted lexicographically).
- **Deep agents**: `create_deep_agent(goal=…/reflect=…)` forwards `memory`,
  `history`, and `verifier` to the inner agent.
- **Stores**: `InMemoryVectorStore` uses monotonic ids; `FileSessionStore` /
  `FileMemoryStore` write atomically (+ a lock on memory `add`).
- **Misc**: `grep` subprocess timeout + global match cap; ShipCrew
  `timeout_seconds` actually pre-empts; `code_execution` cleans up its temp
  script; `diff_traces` stops counting after a reconverging divergence; RAG
  `total_found` reports the true match count.

---

## ✨ Also new

- **180+ new tests** covering every fix above.
- **Six runnable examples** — `examples/13_parallel_tools.py` through
  `examples/18_verifier_guard.py`: parallel tools, cost budgets, multi-turn
  memory, the async runtime, security-hardened tools, and the verifier guard.

---

## Upgrade

```bash
pip install -U shipit-agent
```

Full diff: <https://github.com/shipiit/shipit_agent/compare/v1.0.9...v1.0.10>
