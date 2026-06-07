# shipit-agent 1.0.11 — The control plane

**A Claude Code-grade safety + performance layer for your agents.** 1.0.11 adds
a rule-based **permission engine** (with read-only **plan mode**), **hooks that
can block or rewrite** tool calls, **prompt caching** for ~10× cheaper repeated
calls, and a model-driven **memory tool** for cross-session learning.

> Everything here is **opt-in and backward compatible** — existing agents run
> exactly as before. `pip install -U shipit-agent`.

**1795 tests passing (+50 new) · 0 regressions · ruff clean.**

---

## 🛡️ Permission engine + plan mode

A fast, **rule-based** gate over every tool call — no LLM required (unlike the
`VerifierNetwork`, which it complements).

```python
from shipit_agent import Agent, PermissionEngine

agent = Agent.with_builtins(
    llm=llm,
    permissions=PermissionEngine(
        deny=["bash", "*_delete"],   # never run these
        ask=["sql"],                 # require approval
        allow=["read*", "grep*"],    # always fine
    ),
)
```

- **Modes**: `default`, `acceptEdits` (auto-approve file edits), `plan`
  (read-only — mutating tools denied), `bypass`.
- **`agent.plan("…")`** — research read-only and propose a step-by-step plan
  without taking any action.
- **`permission_callback=fn`** — `(name, args) -> PermissionResult | None` for
  programmatic human-in-the-loop approval.
- Precedence: `deny > mode > allow > ask > callback > default`. A denied call
  emits a `tool_denied` event and a "was NOT run" message so the model re-plans.

## 🪝 Hooks that block & rewrite

`before_tool` hooks can now **return a decision** — deny a call, require
approval, or **rewrite its arguments** (Claude Code's `PreToolUse`):

```python
@hooks.on_before_tool
def guard(name, args):
    if name == "bash" and "rm -rf" in args.get("command", ""):
        return {"decision": "deny", "reason": "destructive command"}
    # return None  → observe-only (fully backward compatible)

@hooks.on_user_prompt
def redact(prompt):
    return prompt.replace("SECRET", "[redacted]")   # rewrite the prompt
```

## ⚡ Prompt caching

The runtime rebuilds the same system prompt + tool schemas every iteration —
the ideal cacheable prefix. 1.0.11 marks it:

```python
from shipit_agent.llms import AnthropicChatLLM
llm = AnthropicChatLLM("claude-opus-4-1", prompt_caching=True)  # default on
```

`cache_control` breakpoints are placed on the tool definitions and system
prompt; responses expose `usage["cache_read_input_tokens"]` /
`["cache_creation_input_tokens"]`, which flow into `CostTracker` so cache reads
bill at ~10% of input. Works for Anthropic, Bedrock (via LiteLLM), and Vertex;
degrades safely on other models.

## 🧠 Memory tool

`ClaudeMemoryTool` is the Anthropic `memory_20250818`-style tool the model
calls to read/write a sandboxed memory directory for true cross-session
learning:

```python
from shipit_agent import Agent, ClaudeMemoryTool
agent = Agent.with_builtins(llm=llm, tools=[ClaudeMemoryTool()])
```

Commands: `view` / `create` / `str_replace` / `insert` / `delete` / `rename`,
confined to `.shipit_workspace/memories` (path-escape rejected).

---

## 📒 New examples & docs

- Notebooks `61_permissions_and_plan_mode`, `62_prompt_caching`,
  `63_claude_memory_tool` (all execute end-to-end offline).
- Docs: **Permissions, plan mode & hooks**, **Prompt caching**, and the
  **Memory tool** pages.

## Coming in 1.0.12

Anthropic **server-side tools** passthrough (code execution, web search/fetch,
computer use), the **Batch API**, native **Citations**, server-side
**context-editing**, and **interleaved thinking** round-trip.

---

Full diff: <https://github.com/shipiit/shipit_agent/compare/v1.0.10...v1.0.11>
