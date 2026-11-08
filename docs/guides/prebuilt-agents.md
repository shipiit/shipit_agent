# Prebuilt Agents

**56 ready-to-use specialists** across developer, design, sales, marketing,
data, finance, and support categories. Load by name, customize, or bring
your own.

## Quick start — `Agent.for_role` (v1.0.15)

The fastest path: one line turns any definition into a runnable agent. The
role's prompt (role + goal + backstory + playbook) becomes the system prompt,
its `tools` list selects the matching built-ins, and its iteration budget is
applied:

```python
from shipit_agent import Agent

analyst  = Agent.for_role("finance-analyst", llm=llm)
writer   = Agent.for_role("marketing-writer", llm=llm)
auditor  = Agent.for_role("security-auditor", llm=llm)

result = analyst.run("Close Q2 and hand me the workbook.")
```

Unknown ids raise a `ValueError` with did-you-mean suggestions
(`"finance"` → *Did you mean: finance-analyst?*). Pass extra `tools=[...]`,
a custom `prompt=`, `mcps=[...]`, or any other `Agent` kwarg to customize.

## Manual assembly (full control)

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry

registry = AgentRegistry.default()
agent_def = registry.get("security-auditor")

agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    max_iterations=agent_def.max_iterations,
)
result = agent.run("Audit my authentication module")
```

## What's new — v1.0.7 added 9 persona specialists

| Persona | Built for | Tools auto-wired |
| --- | --- | --- |
| `code-reviewer-bot` | PR review automation | GitHub + read_file + grep_files + vision |
| `release-engineer`  | Release automation, changelogs, version bumps | GitHub + bash + read_file |
| `figma-designer`    | Read Figma files, post review comments, render frames | Figma + vision |
| `sales-rep`         | Outbound + inbound sales workflows | Salesforce + LinkedIn + Gmail |
| `account-executive` | Pipeline management, deal updates | Salesforce + Gmail + Linear |
| `sales-ops`         | CRM hygiene, lead routing, dashboards | Salesforce + Sheets |
| `recruiter`         | Candidate sourcing + outreach (LinkedIn read-only) | LinkedIn search + Gmail |
| `finance-analyst`   | Stripe/Sheets/PDF/SQL number-crunching | Stripe + PDF + SQL + render_dashboard |
| `customer-support-agent` | Triage + resolve tickets | Zendesk + vision + Slack |

Total roster after v1.0.7 → **56 specialists**. Load any of them the
same way:

```python
from shipit_agent.agents import AgentRegistry

registry = AgentRegistry.default()
spec = registry.get("code-reviewer-bot")
```

The `spec` is a profile — name, description, system prompt, tool list,
suggested model. Hand it to your `Agent` constructor along with your
LLM and a project root.

## Per-persona examples (v1.0.7)

### Code reviewer bot — review a PR

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry

spec = AgentRegistry.default().get("code-reviewer-bot")

agent = Agent.with_builtins(
    llm=opus_llm,
    prompt=spec.system_prompt(),
    max_iterations=spec.max_iterations,
)

result = agent.run(
    "Review pull request shipiit/shipit_agent#142. "
    "Comment inline on any issues."
)
print(result.output)
```

### Release engineer — cut a release

```python
spec = AgentRegistry.default().get("release-engineer")

agent = Agent.with_builtins(
    llm=opus_llm,
    prompt=spec.system_prompt(),
    project_root="/path/to/repo",
)

agent.run(
    "Bump pyproject to 1.1.0, update CHANGELOG with the diff "
    "since v1.0.8, and commit + tag."
)
```

### Figma designer — design review

```python
spec = AgentRegistry.default().get("figma-designer")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Open the homepage hero from Figma file abc123, render it, "
    "and post review comments on layout drift from spec."
)
```

### Sales rep — outreach workflow

```python
spec = AgentRegistry.default().get("sales-rep")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Find 5 senior platform engineers in NYC who worked at Stripe, "
    "log them as leads in Salesforce, and draft a personalised "
    "outreach email for each."
)
```

### Account executive — pipeline sync

```python
spec = AgentRegistry.default().get("account-executive")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Review my open opportunities closing this quarter. Flag "
    "anything stalled >14 days and draft a check-in email."
)
```

### Sales ops — CRM hygiene

```python
spec = AgentRegistry.default().get("sales-ops")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Find all leads in Salesforce missing a region tag and "
    "back-fill it from their company HQ in the master Sheets tab."
)
```

### Recruiter — candidate sourcing

```python
spec = AgentRegistry.default().get("recruiter")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Source 10 senior backend engineers in Berlin with Rust + "
    "distributed-systems experience. Public LinkedIn signals only."
)
```

### Finance analyst — cashflow snapshot

```python
spec = AgentRegistry.default().get("finance-analyst")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Pull last 30d Stripe MRR + churn, cross-reference with the "
    "expense Sheet, and render a one-page cashflow dashboard."
)
```

### Customer support agent — triage

```python
spec = AgentRegistry.default().get("customer-support-agent")

agent = Agent.with_builtins(llm=opus_llm, prompt=spec.system_prompt())

agent.run(
    "Triage all unassigned billing tickets in Zendesk. Apply the "
    "right macro, escalate anything mentioning 'fraud' to #ops in Slack."
)
```

## Power-pair: prebuilt agent + verifier

For production runs where the agent has destructive permissions (e.g.
`sales-rep` writing to Salesforce, `release-engineer` pushing tags),
pair the persona with a `VerifierNetwork`:

```python
from shipit_agent import Agent, VerifierNetwork
from shipit_agent.agents import AgentRegistry

spec = AgentRegistry.default().get("release-engineer")

agent = Agent.with_builtins(
    llm=opus_llm,
    prompt=spec.system_prompt(),
    verifier=VerifierNetwork(
        llm=haiku_llm,
        goal="Cut a clean release. NO force-pushes. NO history rewrites.",
    ),
)
```

The verifier vetoes any tool call that doesn't fit the goal — even
if the persona's system prompt asks for it. Belt-and-suspenders.

## Running a prebuilt agent on your project

The most common use case: load a prebuilt agent and point it at your project directory. The agent gets file tools (read, grep, glob, bash) and can analyze your entire codebase.

### Security audit on a project

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry

registry = AgentRegistry.default()
agent_def = registry.get("security-auditor")

# Point the agent at your project directory
agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    project_root="/path/to/my-project",     # agent works inside this directory
    max_iterations=agent_def.max_iterations,
)

result = agent.run("Perform a full security audit of this project. Check for OWASP Top 10 vulnerabilities.")
print(result.output)
```

### Code review on a project

```python
agent_def = registry.get("code-reviewer")

agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    project_root="/path/to/my-project",
)

result = agent.run("Review the recent changes in src/auth/ for security and code quality issues")
print(result.output)
```

### Architecture review

```python
agent_def = registry.get("architect")

agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    project_root="/path/to/my-project",
)

result = agent.run("Review the project architecture. Identify scalability bottlenecks and suggest improvements.")
print(result.output)
```

### DevOps review

```python
agent_def = registry.get("docker-specialist")

agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    project_root="/path/to/my-project",
)

result = agent.run("Review the Dockerfiles and docker-compose.yml for optimization and security best practices")
print(result.output)
```

### Streaming a project audit

```python
agent_def = registry.get("security-auditor")

agent = Agent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    project_root="/path/to/my-project",
)

# Watch the agent work in real-time
for event in agent.stream("Scan the entire project for hardcoded secrets and API keys"):
    if event.type == "tool_called":
        tool = event.payload.get("tool_name", "")
        args = str(event.payload.get("arguments", ""))[:100]
        print(f"  🔧 {tool}: {args}")
    elif event.type == "tool_completed":
        print(f"  ✅ {event.payload.get('tool_name', '')} done")
    elif event.type == "run_completed":
        print(f"\n=== Audit Complete ===")
        print(event.payload.get("output", "")[:1000])
```

### Using with plain Agent (no built-in tools)

If you only want the prompt persona without built-in tools, use a plain `Agent`:

```python
# Plain Agent — no file tools, just the LLM + prompt
agent = Agent(
    llm=llm,
    prompt=agent_def.system_prompt(),
    max_iterations=agent_def.max_iterations,
)

result = agent.run("Explain the OWASP Top 10 vulnerabilities and how to prevent each one")
```

## Browse agents

```python
registry = AgentRegistry.default()

# All categories
print(registry.categories())
# ['Architecture', 'Code Quality', 'Content', 'DevOps', 'Planning', 'Research', 'Security', 'Testing']

# List by category
for agent_def in registry.list_by_category("Security"):
    print(f"{agent_def.id}: {agent_def.role}")
```

## Search agents

```python
results = registry.search("code review python")
for r in results[:5]:
    print(f"{r.id}: {r.role}")
```

## Agent definition anatomy

Each `AgentDefinition` contains:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique slug (e.g. `"security-auditor"`) |
| `name` | `str` | Display name |
| `role` | `str` | What the agent does |
| `goal` | `str` | Primary objective |
| `backstory` | `str` | Personality/experience context |
| `model` | `str` | Preferred model (`"opus"`, `"sonnet"`, `"haiku"`, `""`) |
| `tools` | `list[str]` | Tool names to attach |
| `skills` | `list[str]` | Skill IDs to attach |
| `max_iterations` | `int` | Default iteration limit |
| `prompt` | `str` | Full system prompt |
| `category` | `str` | Grouping (Security, DevOps, etc.) |
| `tags` | `list[str]` | Search tags |

```python
agent_def = registry.get("architect")
print(agent_def.system_prompt())
# # Role
# You are a Software Architect specializing in scalable, maintainable system design.
# 
# # Goal
# Design robust, scalable architectures...
# 
# # Instructions
# When asked to design or review architecture:
# 1. UNDERSTAND THE CONTEXT...
```

## Built-in agent catalog

### Architecture (5 agents)

| Agent | Role |
|-------|------|
| `architect` | Software architecture specialist for system design and scalability |
| `system-designer` | Distributed systems and microservices design |
| `database-architect` | Schema design, indexing, query optimization |
| `api-designer` | REST/GraphQL API contracts and versioning |
| `frontend-architect` | Component architecture, state management, performance |

### Code Quality (6 agents)

| Agent | Role |
|-------|------|
| `code-reviewer` | Thorough code review with actionable feedback |
| `refactor-cleaner` | Identify and fix code smells, reduce complexity |
| `python-reviewer` | Python-specific best practices and PEP compliance |
| `typescript-reviewer` | TypeScript patterns and type safety |
| `go-reviewer` | Go idioms and concurrency patterns |
| `rust-reviewer` | Rust ownership, lifetimes, unsafe review |

### Security (5 agents)

| Agent | Role |
|-------|------|
| `security-auditor` | OWASP Top 10 audit, dependency CVEs, secrets scan |
| `pentester` | Offensive security testing, exploit chains |
| `threat-modeler` | STRIDE/DREAD threat modeling |
| `security-fixer` | Fix vulnerabilities with safe patches |
| `privacy-reviewer` | GDPR/CCPA compliance, PII detection |

### DevOps (5 agents)

| Agent | Role |
|-------|------|
| `devops-engineer` | CI/CD, infrastructure, deployment |
| `docker-specialist` | Dockerfile optimization, compose, security |
| `k8s-operator` | Kubernetes manifests, helm charts, troubleshooting |
| `ci-cd-builder` | GitHub Actions, GitLab CI, Jenkins pipelines |
| `cloud-architect` | AWS/GCP/Azure infrastructure design |

### Testing (5 agents)

| Agent | Role |
|-------|------|
| `qa-tester` | Test strategy, edge cases, regression testing |
| `tdd-guide` | Test-driven development workflow |
| `e2e-runner` | End-to-end test automation |
| `performance-tester` | Load testing, benchmarking, profiling |
| `api-tester` | API contract testing, fuzzing |

### Planning (4 agents)

| Agent | Role |
|-------|------|
| `planner` | Implementation plans, task breakdown, dependencies |
| `requirements-analyst` | Gather and refine requirements |
| `project-manager` | Scope, timeline, risk assessment |
| `technical-writer` | Documentation, ADRs, RFCs |

### Research (5 agents)

| Agent | Role |
|-------|------|
| `researcher` | Deep web research, source synthesis |
| `competitor-analyst` | Competitive analysis, market positioning |
| `data-analyst` | Data exploration, statistical analysis |
| `doc-lookup` | Find and summarize documentation |
| `trend-researcher` | Technology trends, emerging patterns |

### Content (5 agents)

| Agent | Role |
|-------|------|
| `blog-writer` | Technical blog posts and tutorials |
| `changelog-generator` | Generate changelogs from git history |
| `readme-writer` | Create comprehensive README files |
| `api-doc-writer` | API documentation, OpenAPI specs |
| `tutorial-creator` | Step-by-step coding tutorials |

## Custom agent definitions

```python
from shipit_agent.agents import AgentDefinition

custom = AgentDefinition(
    id="my-compliance-checker",
    name="Compliance Checker",
    role="Regulatory compliance specialist",
    goal="Check code for GDPR, SOX, and PCI-DSS compliance",
    backstory="Former compliance officer at a Fortune 500 bank.",
    tools=["read_file", "grep_files", "glob_files"],
    prompt="Review code for regulatory compliance...",
    category="Compliance",
    tags=["compliance", "gdpr", "pci"],
)
```

## Merging registries

```python
# Project-local agents override built-in ones with the same ID
builtin = AgentRegistry.default()
project = AgentRegistry([custom])
merged = builtin.merge(project)
```

## .shipit/agents/ directory

Drop JSON agent files into your project's `.shipit/agents/` directory:

```
.shipit/
  agents/
    my-custom-agent.json
    researcher.json          # overrides built-in "researcher"
```

```python
local = AgentRegistry.from_directory(".shipit/agents/")
full = AgentRegistry.default().merge(local)
```

## Using with ShipCrew

```python
from shipit_agent.deep.ship_crew import ShipAgent

# Load from registry and wrap as ShipAgent
agent = ShipAgent.from_registry("security-auditor", llm=llm)
```

## Using with DeepAgent

```python
from shipit_agent.deep import DeepAgent

agent_def = registry.get("researcher")
deep = DeepAgent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    verify=True,
    reflect=True,
)
result = deep.run("Research AI agent security best practices")
```

## Streaming

```python
agent_def = registry.get("planner")
agent = Agent.with_builtins(llm=llm, prompt=agent_def.system_prompt())

for event in agent.stream("Plan a microservices migration"):
    print(f"[{event.type}] {event.message}")
```

## Using with Agent (without builtins)

```python
from shipit_agent import Agent

agent_def = registry.get("code-reviewer")

# Plain Agent — no built-in tools, just the system prompt
agent = Agent(
    llm=llm,
    prompt=agent_def.system_prompt(),
    max_iterations=agent_def.max_iterations,
)

result = agent.run("Review this function for bugs")
print(result.output)
```

## Streaming with prebuilt agents

```python
agent_def = registry.get("security-auditor")
agent = Agent(llm=llm, prompt=agent_def.system_prompt())

for event in agent.stream("Check this code for SQL injection"):
    if event.type == "run_started":
        print(f"[START] Agent running...")
    elif event.type == "tool_called":
        print(f"[TOOL]  {event.payload.get('tool_name', 'llm')}")
    elif event.type == "tool_completed":
        print(f"[DONE]  {event.payload.get('tool_name', 'llm')}")
    elif event.type == "run_completed":
        print(f"[END]   Output: {event.payload.get('output', '')[:200]}")
```

## Using with DeepAgent (advanced)

```python
from shipit_agent.deep import DeepAgent

agent_def = registry.get("researcher")

# DeepAgent with verification and reflection
deep = DeepAgent.with_builtins(
    llm=llm,
    prompt=agent_def.system_prompt(),
    verify=True,
    reflect=True,
    max_iterations=12,
)

# Run with full deep agent capabilities
result = deep.run("Research the latest trends in AI agent security")
print(result.output)

# Stream deep agent events
for event in deep.stream("Research quantum computing advances"):
    print(f"[{event.type}] {event.message[:100]}")
```

## DeepAgent with prebuilt sub-agents

```python
from shipit_agent import Agent
from shipit_agent.deep import DeepAgent

# Load prebuilt agents as sub-agents for delegation
researcher_def = registry.get("researcher")
writer_def = registry.get("blog-writer")
reviewer_def = registry.get("code-reviewer")

researcher_agent = Agent(llm=llm, prompt=researcher_def.system_prompt())
writer_agent = Agent(llm=llm, prompt=writer_def.system_prompt())
reviewer_agent = Agent(llm=llm, prompt=reviewer_def.system_prompt())

deep = DeepAgent.with_builtins(
    llm=llm,
    agents=[researcher_agent, writer_agent, reviewer_agent],
)

result = deep.run("Research AI trends, write a blog post, and review it")
```

## Serialization

```python
# To JSON (camelCase keys)
d = agent_def.to_dict()

# From JSON (accepts camelCase or snake_case)
restored = AgentDefinition.from_dict(d)
```

## API reference

| Method | Description |
|--------|-------------|
| `AgentRegistry.default()` | Load built-in 40 agents |
| `AgentRegistry.load(path)` | Load from JSON array file |
| `AgentRegistry.from_directory(path)` | Load from directory of .json files |
| `registry.get(id)` | Get agent by ID (or `None`) |
| `registry.search(query)` | Fuzzy search by name/role/tags |
| `registry.list_by_category(cat)` | Filter by category (case-insensitive) |
| `registry.list_all()` | All agents sorted by ID |
| `registry.categories()` | Sorted unique category list |
| `registry.merge(other)` | Merge; `other` overrides same-ID agents |
| `AgentDefinition.from_dict(d)` | Deserialize from dict |
| `agent_def.to_dict()` | Serialize to dict (camelCase) |
| `agent_def.system_prompt()` | Build full system prompt |
