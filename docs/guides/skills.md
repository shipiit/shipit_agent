---
title: Skills
description: Use packaged skills, attach prebuilt skills to Agent and DeepAgent, and create your own custom skills catalog.
---

# Skills

SHIPIT Agent supports a **skills layer** on top of the normal runtime.
A skill is a reusable instruction block plus metadata that can be:

- loaded from a packaged JSON catalog
- attached explicitly to an `Agent` or `DeepAgent`
- auto-matched from the user prompt
- created locally and saved into your own skill catalog

Skills do not replace tools. They shape how the agent approaches the task.
Use tools for capabilities. Use skills for reusable behavior, workflow, and domain guidance.

---

## What a skill contains

Each `Skill` can include:

| Field group | Fields |
| --- | --- |
| Identity | `id`, `name`, `display_name` |
| Descriptions | `description`, `detailed_description`, `long_description` |
| Discovery | `tags`, `features`, `use_cases`, `how_to_use` |
| Matching | `trigger_phrases` |
| Prompting | `prompt_template` |
| Runtime hints | `tools`, `requirements`, `mcps` |

If a marketplace-style skill has no explicit `prompt_template`, SHIPIT derives prompt text from the skill metadata so it still works at runtime.

---

## Packaged skills catalog

The library now ships with a packaged skills catalog:

```python
from shipit_agent import DEFAULT_SKILLS_PATH, FileSkillRegistry

registry = FileSkillRegistry(DEFAULT_SKILLS_PATH)

print(DEFAULT_SKILLS_PATH)
print(len(registry.list()))
```

Search it:

```python
matches = registry.search("database")
for skill in matches[:5]:
    print(skill.id, "-", skill.description)
```

The packaged file lives at:

```text
shipit_agent/skills/skills.json
```

Detailed discovery example:

```python
from shipit_agent import DEFAULT_SKILLS_PATH, FileSkillRegistry

registry = FileSkillRegistry(DEFAULT_SKILLS_PATH)

print(f"Catalog path: {DEFAULT_SKILLS_PATH}")
print(f"Total skills: {len(registry.list())}")

print("\nTop matches for 'database':")
for skill in registry.search("database")[:5]:
    print(f"- {skill.id}: {skill.description}")

print("\nTop matches for 'workflow':")
for skill in registry.search("workflow")[:5]:
    print(f"- {skill.id}: {skill.description}")
```

---

## Agent with skills

`Agent` supports four main skill entry points:

- `skills=[...]` — always attach these skills
- `default_skill_ids=[...]` — attach known skill ids from the active catalog
- `auto_use_skills=True` — auto-match skills from the user prompt
- `skill_source=...` — point the agent at a custom skill catalog file

### `skills` vs `auto_use_skills`

These two settings are related, but they do different jobs:

| Setting | Behavior |
| --- | --- |
| `skills=[...]` | Explicitly attach these skills for every run |
| `auto_use_skills=False` | Disable prompt-based skill matching and keep behavior deterministic |
| `auto_use_skills=True` | Let the agent auto-match additional skills from the prompt |
| `skill_match_limit` | Cap how many auto-matched skills can be added for a run |

Example:

```python
agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["code-workflow-assistant"],
    auto_use_skills=True,
    skill_match_limit=2,
)
```

What this means:

- `code-workflow-assistant` is always active
- the agent may auto-match more skills from the packaged catalog
- the final run can use both the fixed skills and the auto-matched ones

If you want predictable behavior, set `auto_use_skills=False`.
If you want a more adaptive agent, leave `auto_use_skills=True`.

### Skills improve the approach, not the missing context

Skills help the agent respond with better structure, domain guidance, and workflow.
They do **not** invent the missing details of your task.

Bad prompt:

```python
result = agent.run(
    "Plan this feature, debug the slow path, and suggest database improvements."
)
```

That prompt does not tell the agent:

- which feature
- which service or codebase
- which query or endpoint is slow
- what the constraints are

Better prompt:

```python
result = agent.run(
    """
    We are adding tenant-based billing alerts.

    Context:
    - Backend: FastAPI + PostgreSQL
    - Slow path: GET /api/billing/alerts takes 4.8s
    - Main query joins alerts, tenants, invoices, and users
    - Goal: reduce latency below 500ms

    Please:
    1. Plan the feature work
    2. Debug the likely slow path
    3. Suggest database improvements
    """
)
```

Use this mental model:

- user prompt = the case
- tools = the hands
- skills = the playbook

Complete example:

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["database-architect", "code-workflow-assistant"],
    auto_use_skills=True,
    skill_match_limit=2,
)

result = agent.run(
    """
    We are adding tenant-based billing alerts.

    Context:
    - Backend: FastAPI + PostgreSQL
    - Slow path: GET /api/billing/alerts takes 4.8s
    - Main query joins alerts, tenants, invoices, and users
    - Goal: reduce latency below 500ms

    Please:
    1. Plan the feature work
    2. Debug the likely slow path
    3. Suggest database improvements
    """
)
print(result.output)
```

More explicit end-to-end example:

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["database-architect", "code-workflow-assistant"],
    auto_use_skills=True,
    skill_match_limit=2,
)

prompt = """
We are adding tenant-based billing alerts to an existing FastAPI service.

Project context:
- Backend: FastAPI
- Database: PostgreSQL 15
- Current endpoint: GET /api/billing/alerts
- Current performance: 4.8s p95
- Schema areas involved: alerts, tenants, invoices, users
- Constraint: no breaking API changes this sprint
- Goal: reduce the endpoint below 500ms and produce a safe implementation plan

What I want:
1. Summarize the likely problem areas
2. Propose a concrete implementation plan
3. Suggest database/index/query improvements
4. Call out testing and rollout risks
"""

result = agent.run(prompt)
print(result.output)
```

Attach more skills later:

```python
agent.add_skill("portfolio-website-builder")

for skill in agent.skills:
    print(skill.id)
```

Search the active catalog from the live agent:

```python
for skill in agent.search_skills("workflow")[:5]:
    print(skill.id)
```

Runtime-management example:

```python
agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    auto_use_skills=False,
    skills=["database-architect"],
)

print("Initially attached:")
for skill in agent.skills:
    print("-", skill.id)

print("\nSearch for a writing skill:")
for skill in agent.search_skills("brand")[:3]:
    print("-", skill.id)

agent.add_skill("brand-voice-guide")

print("\nAfter add_skill:")
for skill in agent.skills:
    print("-", skill.id)
```

### Agent constructor parameters

| Parameter | What it does |
| --- | --- |
| `skill_registry` | Supply an already constructed registry |
| `skill_source` | Load skills from a JSON file path |
| `skills` | Attach explicit skills by id or `Skill` object |
| `default_skill_ids` | Attach skill ids from the catalog |
| `auto_use_skills` | Enable prompt-based skill matching |
| `skill_match_limit` | Limit how many auto-matched skills are applied |
| `project_root` | Root directory used by skill-linked file and shell tools. Defaults to `/tmp` |

### Skills can also attach tools automatically

Selected skills do not only affect the prompt. They can also attach stronger built-in tools for that run.

For example, `web-scraper-pro` can bring in tools like:

- `web_search`
- `open_url`
- `playwright_browse`
- `bash`
- `read_file`
- `edit_file`
- `write_file`
- `glob_files`
- `grep_files`

This means skills now shape both:

- how the agent thinks
- which tools the agent can use

Example:

```python
agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["web-scraper-pro", "code-workflow-assistant"],
    auto_use_skills=False,
)

result = agent.run(
    """
    Scrape the target pricing page, inspect the local parser under /tmp,
    patch the output shape, and save the cleaned data.
    """
)

print(result.metadata["used_skills"])
print(result.metadata["used_skill_tools"])
```

`AgentResult.metadata` now exposes:

| Field | Meaning |
| --- | --- |
| `used_skills` | Final list of skill ids used for the run |
| `used_skill_tools` | Extra built-in tools injected because of those skills |

---

## DeepAgent with skills

`DeepAgent` supports the same skill API and passes it through to its inner `Agent`.

```python
from shipit_agent import DeepAgent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

deep_agent = DeepAgent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["database-architect"],
    default_skill_ids=["code-workflow-assistant"],
    auto_use_skills=True,
)

result = deep_agent.run(
    """
    Investigate a slow database-backed feature.

    Context:
    - Service: billing-api
    - Endpoint: GET /api/billing/alerts
    - Current latency: 4.8s p95
    - Database: PostgreSQL
    - Known issue: query joins alerts, tenants, invoices, and users

    Please:
    1. Investigate the likely bottlenecks
    2. Plan a concrete fix
    3. Review the implementation approach
    """
)
print(getattr(result, "output", str(result)))
```

Detailed DeepAgent example:

```python
from shipit_agent import DeepAgent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

deep_agent = DeepAgent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skills=["database-architect"],
    default_skill_ids=["code-workflow-assistant"],
    auto_use_skills=True,
    max_iterations=10,
)

prompt = """
Investigate a slow database-backed feature in the billing-api service.

Context:
- Endpoint: GET /api/billing/alerts
- Current latency: 4.8s p95
- PostgreSQL backend
- Main join path: alerts -> tenants -> invoices -> users
- Requirement: no breaking API changes
- Requirement: keep the rollout safe for multi-tenant data

Please:
1. Investigate likely bottlenecks
2. Produce a step-by-step fix plan
3. Suggest query/index/schema improvements
4. Review the implementation and rollout risks
"""

result = deep_agent.run(prompt)
print(getattr(result, "output", str(result)))
```

Runtime management works the same way:

```python
deep_agent.add_skill("incident-summary-writer")

for skill in deep_agent.skills:
    print(skill.id)
```

Search the catalog:

```python
for skill in deep_agent.search_skills("brand")[:5]:
    print(skill.id)
```

---

## Create your own skills

Use the authoring helpers:

- `skill_id_from_name(...)`
- `create_skill(...)`
- `SkillCatalog(...)`

### Create a skill object

```python
from shipit_agent import create_skill, skill_id_from_name

print(skill_id_from_name("Release Notes Writer"))

skill = create_skill(
    name="Release Notes Writer",
    description="Write concise release notes from code changes.",
    category="Development",
    tags=["release", "changelog", "docs"],
    trigger_phrases=["write release notes", "create a changelog"],
    prompt_template=(
        "Organize the answer into Highlights, Fixes, Known Issues, and Upgrade Notes. "
        "Prefer concise bullets and call out breaking changes clearly."
    ),
)
```

### Save it into a local catalog

```python
from pathlib import Path
from shipit_agent import SkillCatalog

catalog_path = Path("custom_skills.json")
catalog = SkillCatalog(catalog_path)

catalog.add(skill)
```

Or create-and-save in one step:

```python
catalog.create(
    name="Incident Summary Writer",
    description="Turn outage notes into a concise incident summary.",
    category="Operations",
    trigger_phrases=["summarize this incident", "write an incident report"],
    prompt_template="Structure the answer as Summary, Timeline, Root Cause, Impact, and Follow-ups.",
)
```

Detailed custom-skill authoring example:

```python
from pathlib import Path
from shipit_agent import SkillCatalog, create_skill

catalog_path = Path("custom_skills.json")
catalog = SkillCatalog(catalog_path)

release_notes_skill = create_skill(
    name="Release Notes Writer",
    description="Write concise release notes from code changes.",
    category="Development",
    tags=["release", "changelog", "docs"],
    use_cases=[
        "Summarize merged pull requests into release notes",
        "Write internal release notes for engineering and support teams",
    ],
    how_to_use=[
        "Provide merged PR summaries or a change list",
        "Ask for highlights, fixes, known issues, and upgrade notes",
    ],
    trigger_phrases=[
        "write release notes",
        "create a changelog",
        "summarize this release",
    ],
    prompt_template=(
        "Organize the answer into Highlights, Fixes, Known Issues, and Upgrade Notes. "
        "Prefer concise bullets and call out breaking changes clearly."
    ),
)

catalog.add(release_notes_skill)

print("Saved skill ids:")
for skill in catalog.list():
    print("-", skill.id)
```

---

## Use a custom skill catalog in Agent

Point the agent at your custom file and attach the new skill by id:

```python
from shipit_agent import Agent

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skill_source="custom_skills.json",
    auto_use_skills=False,
    skills=["release-notes-writer"],
)

result = agent.run(
    "Write release notes for these changes: fixed login redirect loop and improved dashboard load time."
)
print(result.output)
```

Detailed custom-catalog Agent example:

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skill_source="custom_skills.json",
    auto_use_skills=False,
    skills=["release-notes-writer"],
)

prompt = """
Write release notes for version 2.4.0.

Changes:
- Fixed login redirect loop for expired sessions
- Improved dashboard load time by reducing duplicate invoice queries
- Renamed Billing Settings to Billing Preferences
- Added tenant-based billing alerts
- Known issue: export jobs may still time out for large tenants

Audience:
- customer-facing release notes
- concise wording
- call out anything users need to know before upgrading
"""

result = agent.run(prompt)
print(result.output)
```

## Use the same custom catalog in DeepAgent

```python
from shipit_agent import DeepAgent

deep_agent = DeepAgent.with_builtins(
    llm=llm,
    project_root="/tmp",
    skill_source="custom_skills.json",
    auto_use_skills=False,
    skills=["release-notes-writer"],
)

result = deep_agent.run(
    "Write release notes for these changes: fixed login redirect loop and improved dashboard load time."
)
print(getattr(result, "output", str(result)))
```

Detailed custom-catalog DeepAgent example:

```python
from shipit_agent import DeepAgent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env("bedrock")

deep_agent = DeepAgent.with_builtins(
    llm=llm,
    skill_source="custom_skills.json",
    auto_use_skills=False,
    skills=["release-notes-writer"],
    max_iterations=8,
)

prompt = """
Prepare release notes for version 2.4.0.

Changes:
- Fixed login redirect loop for expired sessions
- Improved dashboard load time by reducing duplicate invoice queries
- Renamed Billing Settings to Billing Preferences
- Added tenant-based billing alerts
- Known issue: export jobs may still time out for large tenants

Please:
1. Organize the release notes cleanly
2. Highlight user-visible changes first
3. Call out the known issue clearly
4. Add upgrade notes only if needed
"""

result = deep_agent.run(prompt)
print(getattr(result, "output", str(result)))
```

---

## When to use skills vs tools

| Use skills when... | Use tools when... |
| --- | --- |
| You want a reusable workflow or style | You need a real capability like web search or file IO |
| You want domain-specific guidance | You need to call an external system |
| You want to preload how the agent should think | You want the agent to do work outside the model |

In practice:

- pair **skills** with **built-in tools**
- use **skills** to steer behavior
- use **tools** to execute

---

## Examples and notebooks

Relevant notebooks in this repo:

- `notebooks/27_skills_catalog_and_usage.ipynb`
- `notebooks/28_create_and_use_custom_skills.ipynb`

These cover:

- fetching all packaged skills
- attaching prebuilt skills to `Agent`
- attaching prebuilt skills to `DeepAgent`
- creating a new custom skill
- saving a custom skill catalog
- using that custom catalog from both agent types

---

## API quick reference

```python
from shipit_agent import (
    Agent,
    DeepAgent,
    Skill,
    SkillCatalog,
    SkillRegistry,
    FileSkillRegistry,
    create_skill,
    skill_id_from_name,
)
```

Main runtime methods:

- `agent.available_skills()`
- `agent.search_skills(query)`
- `agent.add_skill(skill_id_or_skill)`
- `deep_agent.search_skills(query)`
- `deep_agent.add_skill(skill_id_or_skill)`

---

## Recommended pattern

1. Start with the packaged catalog.
2. Search for a skill that already matches your use case.
3. Attach it explicitly with `skills=[...]` for deterministic behavior.
4. Leave `auto_use_skills=True` if you also want prompt-based matching.
5. Create a custom catalog only when your workflow is specific to your team or product.
