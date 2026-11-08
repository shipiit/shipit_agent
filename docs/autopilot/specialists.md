---
title: Specialist agents
description: 47 prebuilt role agents — architects, reviewers, debuggers, researchers, PMs, sales, CS, marketing. Each one a curated prompt + tool preset, ready to drop into an Agent or hand to an Autopilot.
---

# Specialist agents

shipit_agent ships with **47 prebuilt role specialists** loaded from
`shipit_agent/agents/agents.json`. Each one is a complete
`AgentDefinition` — role, goal, backstory, model preference, tool
preset, and a production-quality system prompt.

> **TL;DR** — `AgentRegistry().get("<id>")` gives you a specialist.
> Drop it into `Agent(prompt=spec.prompt, tools=...)` or hand the
> prompt to an Autopilot for long-running role-aligned work.

---

## The 7 new roles (this release)

| ID | Category | What it does |
| --- | --- | --- |
| `generalist-developer` | Engineering | Implement a focused change end-to-end: read code → smallest correct patch → verify → report. No unrelated refactors. |
| `debugger` | Engineering | Reproducer-first root-cause analyst. Refuses to patch until it has a minimal repro + a one-paragraph root-cause statement. |
| `design-reviewer` | Design | UX / UI critic + accessibility auditor. User-task first, contrast numbers non-negotiable, every finding tagged P0 / P1 / P2. |
| `product-manager` | Product | Scope minimally, name non-goals, tie to a measurable metric. Spec format: Problem / Solution / User Flow / Non-Goals / Risks / Metrics / Launch. |
| `sales-outreach` | Sales | B2B account research + first-touch email drafter. One trigger event, one pitch sentence, ≤120-word email. |
| `customer-success` | Customer Success | Read before writing. 30-day plan tied to the customer's stated goal. Red-flag rules for churn prevention. |
| `marketing-writer` | Marketing | Launch / landing copy that converts. Concrete over clever; swaps "blazing fast" for "10k-row table in 120ms". |

Plus the 40 pre-existing specialists (architects, reviewers, devops,
security — see the full list below).

---

## Using a specialist

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.builtins import get_builtin_tools

registry = AgentRegistry()
dev = registry.get("generalist-developer")

agent = Agent(
    llm=llm,
    prompt=dev.prompt,
    tools=get_builtin_tools(project_root="."),
    max_iterations=dev.maxIterations or 40,
    name=dev.name,
)

result = agent.run("Add a docstring to BudgetPolicy.exceeded explaining the return shape.")
print(result.output)
```

---

## Pairing a specialist with Autopilot

For long-form role work — a multi-hour research brief, a multi-PR
security sweep — hand the specialist's prompt to an Autopilot with a
matching budget:

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.tools.research_brief import ResearchBriefTool

researcher = AgentRegistry().get("researcher")
autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Compile a two-page brief on Python type checkers.",
        success_criteria=[
            "Covers mypy / pyright / pyre",
            "Each checker has a one-line tradeoff",
            "Ends with a recommendation table",
        ],
    ),
    tools=[ResearchBriefTool()],
    budget=BudgetPolicy(max_iterations=6, max_seconds=600),
    critic=True,
    artifacts=True,
    prompt=researcher.prompt,
)
autopilot.run(run_id="type-checkers-brief")
```

---

## Full roster

### Architecture (5)
- `architect` — Software Architect
- `system-designer` — Distributed Systems Designer
- `database-architect` — Database Architect
- `api-designer` — API Designer
- `frontend-architect` — Frontend Architect

### Engineering (9)
- `code-reviewer` — Senior Code Reviewer
- `refactor-cleaner` — Refactor Cleaner
- `python-reviewer` · `typescript-reviewer` · `go-reviewer` · `rust-reviewer`
- **`generalist-developer`** · **`debugger`**

### Security (4)
- `security-auditor` · `pentester` · `threat-modeler` · `security-fixer`

### Privacy (1)
- `privacy-reviewer`

### DevOps (4)
- `devops-engineer` · `docker-specialist` · `k8s-operator` · `ci-cd-builder`

### Design (1)
- **`design-reviewer`**

### Product (1)
- **`product-manager`**

### Sales (1)
- **`sales-outreach`**

### Customer Success (1)
- **`customer-success`**

### Marketing (1)
- **`marketing-writer`**

### Research (1)
- `researcher`

### … plus 18 more (data, docs, QA, support, writing)

Run `AgentRegistry().all()` to enumerate the full list or inspect
`shipit_agent/agents/agents.json` directly.

---

## Adding your own specialist

Drop a JSON object into `agents.json`:

```json
{
  "id": "compliance-reviewer",
  "name": "Compliance Reviewer",
  "role": "SOC 2 / HIPAA / GDPR compliance auditor",
  "goal": "Evaluate changes against the organisation's controls.",
  "backstory": "You have led four SOC 2 Type II audits...",
  "model": "opus",
  "tools": ["read_file", "grep_search", "list_directory"],
  "skills": [],
  "maxIterations": 15,
  "prompt": "When reviewing a change:\n\n1. ...",
  "category": "Compliance",
  "tags": ["compliance", "audit"],
  "version": "1.0.0",
  "author": "you"
}
```

`AgentRegistry()` picks it up automatically. Commit the JSON to share
the specialist with your team.

---

## Notebooks

- `notebooks/40_specialists_developer_debugger_researcher.ipynb`
- `notebooks/41_specialists_design_pm_sales_cs_marketing.ipynb`
- `notebooks/44_complete_tour.ipynb` — specialists in context with Autopilot + fan-out + critic + artifacts.
