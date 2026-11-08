---
title: Plugins
description: Extend the agent without editing it — a plugin is a drop-in directory of tools and lifecycle hooks, discovered from your own folder or a pip package, with user-over-bundled precedence.
---

# Plugins

A plugin is the way you **add to the agent without opening it up**. Drop a
directory in, and its tools and lifecycle hooks become part of every agent you
build — no fork, no patch, no waiting for a release.

A plugin is a clean directory with two files:

```
my-plugins/
  redact-secrets/
    plugin.yaml     # what it is
    plugin.py       # def register(reg): ...
```

```python
from shipit_agent import Agent
from shipit_agent.plugins import list_plugins

for p in list_plugins():
    print(p.icon, p.name, "—", p.description)

agent = Agent(llm=llm, plugins=["audit-log", "word-count"])
agent.run("Count the words in this paragraph.")
```

`Agent(plugins=[...])` folds each plugin's tools and hooks in at construction.
Pass plugin **names** (resolved from the catalog) or **`Plugin` objects**. When
the list is empty it costs nothing.

## What a plugin can do

A plugin contributes two things, either or both:

- **Tools** — anything the agent accepts in `tools=`. A plugin can ship one tool
  or a whole pack.
- **Lifecycle hooks** — callbacks that run around the loop: before/after each
  LLM call, before/after each tool call, and on the incoming user prompt. A
  before-tool hook can even **deny or rewrite** a call; a prompt hook can
  **redact** the prompt. (See the [Hooks guide](hooks.md) for the full contract.)

Both are handed to your `register()` through a small `PluginRegistrar`.

## The manifest — `plugin.yaml`

Declarative metadata the loader validates and a UI can render:

```yaml
plugin_version: 1
name: redact-secrets            # lowercase, [A-Za-z0-9_-]
description: Strip API keys from prompts and tool output.
version: 1.0.0
author: you@example.com
kind: standalone                # the only kind today
icon: "🔒"
provides_tools: []              # declared tool names (optional, for a UI)
hooks: [user_prompt, after_tool]
```

An invalid manifest is **skipped with a diagnostic** — it never crashes the
catalog. A manifest that names an unknown hook point is rejected at parse time,
so a plugin hook is always a real, wired callback — never a dead declaration.

The valid hook points, each mapping one-to-one onto the agent's
[`AgentHooks`](hooks.md) surface:

| Hook point | Runs | Can |
| --- | --- | --- |
| `user_prompt` | on the incoming prompt | rewrite or block it |
| `before_llm` | before each model call | observe messages + tools |
| `after_llm` | after each model response | observe the response |
| `before_tool` | before each tool call | allow, deny, or rewrite args |
| `after_tool` | after each tool result | observe or transform the result |

## The code — `plugin.py`

One function, `register(reg)`, called with a `PluginRegistrar`. Use
`reg.add_tool(...)` and `reg.add_hook(point, fn)`:

```python
# my-plugins/redact-secrets/plugin.py
import re
from typing import Any

_KEY = re.compile(r"\b(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")

def _redact(text: str) -> str:
    return _KEY.sub("[redacted]", text)

def register(reg: Any) -> None:
    # Rewrite the incoming prompt (return a new string to replace it).
    reg.add_hook("user_prompt", lambda prompt: _redact(prompt))

    # Transform every tool result (return a new value to replace it).
    reg.add_hook("after_tool", lambda name, result: _redact(str(result)))
```

`register` runs **only when the plugin is applied to an agent** — discovery
reads manifests without importing your code, so a broken or heavy plugin.py
can't slow down `list_plugins()`.

### A tool-pack plugin

A plugin that adds a tool ships the tool right in `plugin.py`:

```python
# my-plugins/uuid/plugin.py
import uuid
from typing import Any
from shipit_agent.tools.base import ToolOutput

class NewUuidTool:
    name = "new_uuid"
    description = "Generate a random UUID v4."
    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": {}}}}
    def run(self, context: Any = None, **kwargs: Any) -> ToolOutput:
        return ToolOutput(text=str(uuid.uuid4()), metadata={})

def register(reg: Any) -> None:
    reg.add_tool(NewUuidTool())
```

## Adding your own plugins — three sources

Plugins are discovered from three places, in **increasing precedence** so your
own plugin always wins over a bundled one of the same name:

### 1. A directory you point at

Set `SHIPIT_PLUGINS_DIR` to a folder of plugin directories — the simplest way
to add plugins to an app you don't own:

```bash
export SHIPIT_PLUGINS_DIR=/opt/myapp/plugins
# /opt/myapp/plugins/redact-secrets/plugin.yaml + plugin.py
```

Or drop them under `$SHIPIT_HOME/plugins`. Either way, no install step — the
directory *is* the registration.

```python
from shipit_agent.plugins import list_plugins
# your redact-secrets plugin now appears alongside the bundled ones:
print([p.name for p in list_plugins()])
```

### 2. A pip package (share a plugin)

Ship a plugin as a package by advertising the `shipit_agent.plugins`
entry-point group. Anyone who `pip install`s your package gets the plugin
automatically:

```toml
# your package's pyproject.toml
[project.entry-points."shipit_agent.plugins"]
redact-secrets = "my_package.plugin:make_plugin"
```

```python
# my_package/plugin.py
from shipit_agent.plugins import Plugin
from . import register           # your register(reg)

def make_plugin() -> Plugin:
    return Plugin(name="redact-secrets", description="…", register=register)
```

Entry-point plugins have the **highest** precedence, so a distributed plugin can
intentionally replace a bundled default.

> **Opt-in for security.** Loading an entry-point plugin runs code from an
> installed package, so shipit does **not** auto-load them — a stray
> `pip install` can never inject a plugin on its own. Turn it on deliberately
> when you trust your environment:
>
> ```bash
> export SHIPIT_PLUGIN_ENTRY_POINTS=1
> ```
>
> Bundled and user-directory plugins are always discovered; only the
> pip-package source is gated.

### 3. Bundled

The plugins that ship with shipit live in `shipit_agent/plugins/catalog/`. Two
examples ship today: **`audit-log`** (an observe-only `after_tool` logger) and
**`word-count`** (a standalone tool pack). They're the reference for writing
your own.

### Precedence, in one line

```
bundled  <  user directory  <  pip entry point        (last wins by name)
```

## Inspecting the catalog

```python
from shipit_agent.plugins import list_plugins, get_plugin, PLUGIN_DIAGNOSTICS

list_plugins()                      # every discovered plugin
get_plugin("audit-log")             # one, by name (or None)
PLUGIN_DIAGNOSTICS                   # [(source, error)] for anything skipped
```

`PLUGIN_DIAGNOSTICS` is how you find a plugin that didn't load — a bad manifest,
a `plugin.py` that raised on import, an entry point that returned the wrong
type. Nothing is silent; nothing is fatal.

## Using plugins with an agent

```python
from shipit_agent import Agent
from shipit_agent.plugins import get_plugin

# By name — resolved from the catalog:
agent = Agent(llm=llm, plugins=["audit-log", "word-count"])

# By object — build one inline, no catalog needed:
from shipit_agent.plugins import Plugin
inline = Plugin(name="tap", register=lambda reg:
                reg.add_hook("after_tool", lambda n, r: print("ran", n)))
agent = Agent(llm=llm, plugins=[inline])
```

A plugin's tools join the agent's tool belt and its hooks run alongside any
`hooks=` you pass yourself — the two compose, they don't replace each other.

## How it fits the rest of the library

Plugins are the general extension mechanism; connectors and providers are
specialised catalogs built on the same one-directory-per-unit idea:

- **[Connections](connections.md)** — a catalog of MCP servers (integrations).
- **Providers** — a catalog of model providers.
- **Plugins** — a catalog of tool + hook packs, *plus* your own directories and
  pip packages.

If you want to bundle a set of tools and behaviours and hand them to any agent —
yours or someone else's — a plugin is the unit.

## See also

- [Hooks](hooks.md) — the full before/after contract a plugin hook plugs into.
- [Creating custom tools](custom-tools.md) — the tool shape a plugin ships.
- [Connections](connections.md) — the connector catalog, same pattern.
