# SHIPIT Agent v1.0.4 — Announcement Kit

Copy-paste-ready posts for announcing v1.0.4 across platforms.

---

## Twitter/X Thread

### Tweet 1 (Main)

```
shipit-agent v1.0.4 is out 🚀

Skills now auto-attach the right tools. 37 skill bundles. 32 upgraded tool prompts. Agents work longer on complex tasks.

pip install shipit-agent==1.0.4

Docs: https://docs.shipiit.com/
GitHub: https://github.com/shipiit/shipit_agent/releases/tag/v1.0.4

🧵 What's new ↓
```

### Tweet 2

```
Skills → Tools, automatically.

Every skill now declares which tools it needs. Attach "full-stack-developer" and the agent gets 13 tools: write_file, edit_file, bash, run_code, web_search, plan_task, verify_output...

No manual wiring. Just:

skills=["full-stack-developer"]
```

### Tweet 3

```
All 32 tool prompts rewritten.

Each tool now has:
• Decision trees (which tool to pick)
• Anti-patterns (what NOT to do)
• Workflow chains (glob → read → edit → verify)
• Cross-tool coordination

The agent picks the right tool on the first try.
```

### Tweet 4

```
Agents work longer when skills are active.

Default max_iterations auto-boosts 4 → 8 when skills inject extra tools. Your explicit overrides are always respected.

No more "agent cut off mid-task" on skill-driven workflows.
```

### Tweet 5

```
Streaming + chat + memory, all with skills.

for event in agent.stream("Build this project"):
    print(event.type, event.message)

chat = agent.chat_session(session_id="debug")
chat.send("Billing API is slow")
chat.send("Show me the indexes")  # remembers context
```

### Tweet 6

```
3 notebooks show it in action:

📓 27 — Full tour: streaming, chat, project build
📓 29 — DeepAgent + verify + reflect + sub-agents
📓 30 — Build a real FastAPI project from scratch across 6 steps with 5 different skills

50+ bash commands unblocked. 32 tests. All passing.
```

---

## LinkedIn

```
SHIPIT Agent v1.0.4 — Skills Power-Up

Just shipped a major update to shipit-agent, our open-source Python agent library.

The big idea: skills now auto-attach the right tools.

When you tell the agent to use the "full-stack-developer" skill, it automatically gets 13 tools — write_file, edit_file, bash, run_code, web_search, plan_task, verify_output, and more. No manual wiring. No guessing which tools to include.

What's in v1.0.4:

→ 37 skill-to-tool bundles (up from 10). Every packaged skill now declares exactly which built-in tools it needs. The agent gets the right toolkit automatically.

→ All 32 tool prompts rewritten. Each tool now includes decision trees ("Need to search content? → grep_files. Need a filename? → glob_files"), anti-patterns, workflow chains, and cross-tool coordination hints. The agent picks the right tool on the first try.

→ Automatic iteration boost. When skills inject extra tools, the agent's iteration budget auto-increases from 4 to 8 — so skill-driven workflows actually complete instead of cutting off mid-task.

→ 50+ bash commands unblocked. mkdir, curl, docker, kubectl, terraform, go, cargo, eslint — all the commands agents actually need in real-world development workflows.

→ Streaming + multi-turn chat + memory. Full event streaming with skills. Persistent chat sessions where the agent remembers context across turns. No more "what project are you working on?" on every follow-up.

→ 3 notebooks showing real-world usage. Build a complete FastAPI project from scratch. Web scraping with saved results. Security audits. DevOps pipelines. Multi-turn iterative development with DeepAgent chat.

→ 32 tests. All passing.

The philosophy: skills shape HOW the agent thinks. Tools give it HANDS. This release makes sure they work together seamlessly.

pip install shipit-agent==1.0.4
Docs: https://docs.shipiit.com/
GitHub: https://github.com/shipiit/shipit_agent

#opensource #python #ai #agents #llm #developer #shipitagent
```

---

## Reddit (r/Python, r/MachineLearning, r/LocalLLaMA)

### Title

```
shipit-agent v1.0.4: Skills now auto-attach tools, 32 upgraded prompts, iteration boost, streaming + chat
```

### Body

````
Just released v1.0.4 of shipit-agent — an open-source Python library for building tool-using LLM agents.

The headline: skills now automatically bring the right tools.

Previously you had to manually wire tools for each skill. Now every skill declares what it needs. Attach `skills=["full-stack-developer"]` and the agent gets 13 tools (write_file, bash, web_search, etc.) without any extra config.

**What's new:**

- **37 skill tool bundles** — every packaged skill (full-stack-developer, web-scraper-pro, security-engineer, devops-automation, etc.) auto-attaches its tools
- **32 tool prompts rewritten** — each tool has decision trees, anti-patterns, and workflow guidance so the agent picks the right tool
- **Iteration boost** — agents auto-get more turns (4→8) when skills inject tools, so complex workflows don't cut off
- **50+ bash commands** — mkdir, curl, docker, kubectl, go, cargo all unblocked
- **Streaming + chat + memory** — full event streaming with skills, persistent multi-turn chat with context retention
- **3 notebooks** — real project building, web scraping, security audits, DeepAgent with verification/reflection

**Quick example:**

```python
from shipit_agent import Agent
from shipit_agent.stores import InMemoryMemoryStore

agent = Agent.with_builtins(
    llm=llm,
    project_root="/tmp/my-project",
    skills=["full-stack-developer"],
    memory_store=InMemoryMemoryStore(),
)

# Agent gets 13 tools, 8 iterations, and domain guidance — automatically
result = agent.run("Create a FastAPI project with User and Task models, CRUD endpoints, and a Dockerfile.")
````

- Docs: https://docs.shipiit.com/
- GitHub: https://github.com/shipiit/shipit_agent
- PyPI: `pip install shipit-agent==1.0.4`

MIT licensed. Works with OpenAI, Anthropic, Bedrock, Groq, Together, Ollama, and more.

```

---

## Hacker News

### Title

```

Show HN: SHIPIT Agent v1.0.4 – Python agent lib where skills auto-attach the right tools

```

### Body

```

SHIPIT Agent is an open-source Python library for building tool-using LLM agents. v1.0.4 just shipped with a skill system that automatically wires tools.

The idea: you attach a "skill" (like full-stack-developer or security-engineer) and the agent automatically gets the tools it needs — write_file, bash, web_search, etc. No manual tool configuration.

What changed in v1.0.4:

- 37 skill-to-tool bundles (every packaged skill auto-attaches tools)
- 32 tool prompts rewritten with decision trees and anti-patterns
- Agents auto-get more iterations when skills inject tools
- 50+ bash commands unblocked (mkdir, curl, docker, go, cargo)
- Streaming + multi-turn chat with memory
- 3 real-world notebooks (build a FastAPI project, security audit, DevOps pipeline)

Example:

    agent = Agent.with_builtins(
        llm=llm,
        skills=["full-stack-developer"],
        memory_store=InMemoryMemoryStore(),
    )
    result = agent.run("Create a FastAPI project with models, routes, Docker, and CI.")

Works with OpenAI, Anthropic, Bedrock, Groq, Together, Ollama. MIT licensed.

Docs: https://docs.shipiit.com/
GitHub: https://github.com/shipiit/shipit_agent

```

---

## Dev.to / Hashnode Blog Post

### Title

```

SHIPIT Agent v1.0.4: Skills That Actually Wire Their Own Tools

````

### Body

```markdown
## The Problem

You build an agent with skills like "full-stack-developer" or "security-engineer". The skill tells the agent HOW to approach the task. But the agent still needs the right TOOLS — write_file, bash, web_search, run_code.

Previously you had to wire those manually. Forget one and the agent fumbles.

## The Fix

In v1.0.4, every skill declares the tools it needs. Attach the skill, get the tools. Automatically.

```python
agent = Agent.with_builtins(
    llm=llm,
    skills=["full-stack-developer"],  # → 13 tools auto-attached
)
````

The `full-stack-developer` skill brings: read_file, edit_file, write_file, glob_files, grep_files, bash, run_code, workspace_files, web_search, open_url, playwright_browse, plan_task, verify_output.

37 skills. 37 bundles. Zero manual wiring.

## What Else Shipped

**32 tool prompts rewritten.** Each tool now has decision trees:

- "Need to search file content?" → grep_files
- "Need to find a file by name?" → glob_files
- "Need to edit a few lines?" → read_file then edit_file
- "Need to create a new file?" → write_file

Plus anti-patterns ("Don't use cat when read_file exists") and workflow chains.

**Iteration boost.** When skills inject tools, max_iterations auto-increases from 4 to 8. Complex skill-driven workflows complete instead of cutting off.

**50+ bash commands.** mkdir, curl, docker, kubectl, terraform, go, cargo — all unblocked.

**Streaming + chat + memory.**

```python
# Stream events in real time
for event in agent.stream("Build a Dockerfile"):
    if event.type == "tool_called":
        print(f"[tool] {event.message}")

# Multi-turn chat with context retention
chat = agent.chat_session(session_id="debug")
chat.send("Billing API is slow — 4.8s p95")
chat.send("Show me the CREATE INDEX statements")  # remembers context
```

**3 notebooks:**

- **27**: Full tour — streaming, chat, project build, web scraping
- **29**: DeepAgent + verify + reflect + sub-agents
- **30**: Build a real FastAPI project across 6 steps with 5 skills

## Install

```bash
pip install shipit-agent==1.0.4
```

- [Docs](https://docs.shipiit.com/)
- [GitHub](https://github.com/shipiit/shipit_agent)
- [Skills Guide](https://docs.shipiit.com/guides/skills/)

MIT licensed. Works with OpenAI, Anthropic, AWS Bedrock, Groq, Together, Ollama, and more.

```

---

## Discord / Slack (short)

```

🚀 shipit-agent v1.0.4

Skills now auto-attach tools. 37 bundles. 32 upgraded prompts. Iteration boost. Streaming + chat + memory.

pip install shipit-agent==1.0.4
Docs: docs.shipiit.com

Highlights:
• Attach "full-stack-developer" → agent gets 13 tools automatically
• Tool prompts have decision trees so the agent picks the right one
• max_iterations auto-boosts 4→8 when skills are active
• 50+ bash commands unblocked (mkdir, curl, docker, go, cargo)
• 3 notebooks: real project build, DeepAgent + verify, web scraping

```

---

## Product Hunt (tagline + description)

### Tagline

```

Python agent library where skills auto-wire the right tools

```

### Description

```

SHIPIT Agent is an open-source Python library for building LLM-powered agents with tools, skills, streaming, and memory.

v1.0.4 introduces automatic tool linking — attach a skill like "full-stack-developer" and the agent gets 13 tools (write_file, bash, web_search, plan_task...) without any configuration.

37 packaged skills across development, DevOps, security, marketing, and research. All 32 tool prompts rewritten with decision trees. Agents auto-get more iterations for complex tasks.

Works with OpenAI, Anthropic, AWS Bedrock, Google, Groq, Together, Ollama. MIT licensed.

```

```
