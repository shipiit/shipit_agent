# `shipit_agent.agent_setup`

Building an `Agent`: preparation, the built-in tool catalogue, profiles, templates, configuration and the doctor.

| Module | What it does |
|---|---|
| `builtins.py` | Built-in tool catalogue — all 30+ tools that ship with SHIPIT Agent |
| `config.py` | Configuration that can always be deleted |
| `doctor.py` | Health checks for an agent's configuration: model credentials, tools, MCP servers and settings |
| `preparation.py` | Skill, delegation, tool, and permission preparation for :class:`Agent` |
| `profiles.py` | Named, reusable agent configurations and a builder for them |
| `templates.py` | Prompt templates with named placeholders |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
