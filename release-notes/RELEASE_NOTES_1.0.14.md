# shipit-agent 1.0.14 — The SHIPIT Workspace

Point an agent at a repo and it just works — **project instructions, slash
commands, a declarative policy file, and live task tracking.** All opt-in and
backward compatible.

> `pip install -U shipit-agent`

**1884 tests passing (+30 new) · 0 regressions · ruff clean.**

---

## 📄 Project memory — `SHIPIT.md` / `AGENTS.md`

Drop a `SHIPIT.md` (or the conventional `AGENTS.md`) at your repo root and every
agent pointed at that project picks it up automatically — the SHIPIT answer to a
project instructions file.

```python
agent = Agent.with_builtins(llm=llm, project_root="/my/repo")
# SHIPIT.md / AGENTS.md / .shipit/SHIPIT.md (+ ~/.shipit/SHIPIT.md) auto-load
# into the system prompt. @path imports are resolved.
```

Opt out with `auto_project_memory=False`; load directly with
`load_project_memory(project_root)`.

## ⚡ Slash commands — `.shipit/commands/`

```python
# .shipit/commands/review.md  ->  "Review $ARGUMENTS for bugs and style."
agent.run("/review src/app.py")     # expands to the command body
```

`$ARGUMENTS` and `$1`, `$2`, … are substituted; YAML frontmatter is stripped;
an unknown `/cmd` passes through unchanged. APIs: `discover_commands()`,
`expand_command()`.

## ⚙️ Declarative config — `.shipit/settings.json`

```json
{
  "model": "bedrock/us.anthropic.claude-3-5-sonnet-20240620-v1:0",
  "permissions": { "deny": ["bash", "*_delete"], "ask": ["sql"] },
  "env": { "SHIPIT_LLM_PROVIDER": "bedrock" }
}
```

```python
agent = Agent.for_project(llm=llm, project_root="/my/repo")
```

**`Agent.for_project()`** loads `.shipit/settings.json` → a permission engine,
the full builtin tools, project memory, and slash commands — in one call. Works
with **any** LLM provider. APIs: `load_settings()`, `WorkspaceSettings`.

## ✅ Live task tracking — `TodoTool`

```python
agent = Agent.with_builtins(llm=llm)   # `todo` tool included
```

The model maintains a checklist as it works (`pending → in_progress →
completed`, replace semantics), stored on `context.state["todos"]` with a
rendered checklist + progress summary — the SHIPIT TodoWrite that makes long
agentic runs observable and smooth.

---

## 📒 Examples & docs

- Notebooks `67_shipit_workspace` and `68_todo_tool` (run offline).
- Docs: **The SHIPIT Workspace** and **TodoTool** pages.

---

Full diff: <https://github.com/shipiit/shipit_agent/compare/v1.0.13...v1.0.14>
