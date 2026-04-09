---
title: Reasoning Helpers
description: Tools that help the agent decompose problems, build prompts, verify outputs, synthesize evidence, and weigh decisions.
---

# Reasoning Helpers

These tools don't *do* anything in the world — they help the agent **think more carefully** before or after acting. Use them when the task involves judgment, comparison, verification, or breaking apart a complex problem.

| Tool | Tool ID | Purpose |
|---|---|---|
| `PromptTool` | `build_prompt` | Generate or refine a system prompt |
| `VerifierTool` | `verify_output` | Check whether content satisfies criteria |
| `ThoughtDecompositionTool` | `decompose_problem` | Break a problem into workstreams + risks |
| `EvidenceSynthesisTool` | `synthesize_evidence` | Turn observations into facts + recommendations |
| `DecisionMatrixTool` | `decision_matrix` | Score options against criteria |
| `SubAgentTool` | `sub_agent` | Delegate a focused subtask to a lightweight LLM call |

---

## `build_prompt`

**Class:** `PromptTool`
**Module:** `shipit_agent.tools.prompt`
**Tool ID:** `build_prompt`

Generates or refines a system prompt from goals, constraints, and style instructions. Useful for **meta-agents** that build other agents on the fly.

### When to use

- You're building a system that spawns sub-agents and needs each one to have a tailored prompt
- You want to **iteratively improve** an existing prompt based on observed failures
- You need to express a complex set of constraints in coherent prose

### Schema

```json
{
  "name": "build_prompt",
  "parameters": {
    "type": "object",
    "properties": {
      "role":        { "type": "string", "description": "Who/what the agent is — e.g. 'a senior backend engineer'" },
      "goals":       { "type": "array",  "description": "What the agent should accomplish" },
      "constraints": { "type": "array",  "description": "What the agent must not do" },
      "style":       { "type": "string", "description": "Tone and communication style" }
    },
    "required": ["role"]
  }
}
```

### Example

```python
from shipit_agent import Agent, PromptTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[PromptTool()],
)

result = agent.run(
    "Build a system prompt for a code-review agent that focuses on "
    "security vulnerabilities and refuses to make unsafe suggestions."
)
print(result.output)  # → A polished system prompt ready to drop into another Agent
```

---

## `verify_output`

**Class:** `VerifierTool`
**Module:** `shipit_agent.tools.verifier`
**Tool ID:** `verify_output`

Checks whether content satisfies a set of required criteria. Returns a structured verdict (`pass` / `fail` / `partial`) with reasons.

### When to use

- After generating a piece of content, **before** showing it to the user
- As a **gate** in a multi-step pipeline (don't proceed if verification fails)
- To enforce **structural requirements** (e.g. "must contain a markdown table", "must cite at least 2 sources")

### Schema

```json
{
  "name": "verify_output",
  "parameters": {
    "type": "object",
    "properties": {
      "content":  { "type": "string", "description": "The content to verify" },
      "criteria": { "type": "array",  "description": "List of requirements the content must satisfy" }
    },
    "required": ["content", "criteria"]
  }
}
```

### Example

```python
result = agent.run(
    "Write a product launch email. Then verify it meets these criteria: "
    "1) under 200 words, "
    "2) contains a clear call-to-action, "
    "3) mentions the launch date."
)
```

---

## `decompose_problem`

**Class:** `ThoughtDecompositionTool`
**Module:** `shipit_agent.tools.thought_decomposition`
**Tool ID:** `decompose_problem`

Breaks a complex problem into **workstreams**, **assumptions**, **risks**, **evidence needs**, and **next actions**. Ideal first step for any non-trivial planning task.

### When to use

- The task is too big to attack head-on
- You need to **identify unknowns** before committing to a plan
- You want to surface **risks** early in the process

### Output structure

```
## Workstreams
1. ...
2. ...

## Assumptions
- ...

## Risks
- ...

## Evidence needs
- ...

## Next actions
1. ...
```

### Example

```python
result = agent.run(
    "Decompose: How do I migrate our PostgreSQL database from on-prem to AWS RDS "
    "with minimal downtime?"
)
```

---

## `synthesize_evidence`

**Class:** `EvidenceSynthesisTool`
**Module:** `shipit_agent.tools.evidence_synthesis`
**Tool ID:** `synthesize_evidence`

Turns raw observations (from tool calls, web fetches, file reads) into structured **facts**, **inferences**, **gaps**, and **recommendations**. The natural counterpart to `decompose_problem` — you decompose to plan, then synthesize to conclude.

### When to use

- After gathering data from multiple sources, before writing a report
- When the conclusion isn't obvious from any single piece of evidence
- To **flag what's missing** so the agent knows whether to search for more

### Output structure

```
## Facts (directly observed)
- ...

## Inferences (derived from facts)
- ...

## Gaps (unknown but relevant)
- ...

## Recommendations
- ...
```

### Example

```python
# Run after several web_search + open_url calls
result = agent.run(
    "Synthesize the evidence we've gathered about Kubernetes vs Nomad and "
    "recommend which one to adopt."
)
```

---

## `decision_matrix`

**Class:** `DecisionMatrixTool`
**Module:** `shipit_agent.tools.decision_matrix`
**Tool ID:** `decision_matrix`

Compares **N options** against **M criteria** and recommends the strongest choice. Outputs a markdown matrix with scores plus a written recommendation.

### When to use

- The agent has multiple viable options and needs to **pick one with reasoning**
- You want a **transparent decision** the user can audit and override
- Stakeholders disagree and you want a structured framework

### Schema

```json
{
  "name": "decision_matrix",
  "parameters": {
    "type": "object",
    "properties": {
      "options":  { "type": "array", "description": "List of options to compare" },
      "criteria": { "type": "array", "description": "List of criteria to score against" },
      "weights":  { "type": "object", "description": "Optional per-criterion weight (defaults to 1.0 each)" }
    },
    "required": ["options", "criteria"]
  }
}
```

### Output

```
| Option       | Cost | Speed | Reliability | Total |
|--------------|------|-------|-------------|-------|
| AWS Lambda   | 8    | 9     | 9           | 26    |
| Cloud Run    | 7    | 8     | 9           | 24    |
| Self-hosted  | 9    | 6     | 7           | 22    |

**Recommendation:** AWS Lambda. Highest total score, especially strong on speed and reliability.
**Trade-off:** Vendor lock-in is the main downside if you need to migrate later.
```

### Example

```python
result = agent.run(
    "Compare AWS Lambda, Google Cloud Run, and self-hosted Kubernetes for "
    "running our 10-job-per-day batch pipeline. Use cost, speed, reliability, "
    "and operational complexity as criteria. Recommend the best fit."
)
```

---

## `sub_agent`

**Class:** `SubAgentTool`
**Module:** `shipit_agent.tools.sub_agent`
**Tool ID:** `sub_agent`

Delegates a **focused subtask** to a lightweight LLM call without spinning up a full nested Agent runtime. Useful for **task fan-out** patterns where the parent agent decomposes work and farms out pieces.

### When to use

- The parent agent's main loop is large and you want to isolate a subtask
- You need to run **parallel research** across multiple topics
- You want to use a **cheaper model** for a routine subtask while keeping the main agent on a powerful one

### Schema

```json
{
  "name": "sub_agent",
  "parameters": {
    "type": "object",
    "properties": {
      "task":          { "type": "string", "description": "The focused subtask to perform" },
      "context":       { "type": "string", "description": "Background context the subagent needs" },
      "output_format": { "type": "string", "description": "Expected output format (e.g. 'one paragraph', 'JSON list')" }
    },
    "required": ["task"]
  }
}
```

### Configuration

```python
from shipit_agent import SubAgentTool
from shipit_agent.llms import OpenAIChatLLM

# Sub-agent uses a cheaper model than the main agent
sub_tool = SubAgentTool(llm=OpenAIChatLLM(model="gpt-4o-mini"))

main_agent = Agent(
    llm=OpenAIChatLLM(model="o3-mini"),  # main = expensive reasoning model
    tools=[sub_tool],                     # subtasks = cheap model
)
```

### Example

```python
result = agent.run(
    "Research three competitors (Datadog, Grafana, New Relic) and summarize "
    "each one's pricing model in one paragraph. Use sub_agent for each."
)
```

The parent calls `sub_agent` three times in parallel, gets three paragraphs back, and stitches them into the final answer.

### Notes

- `SubAgentTool` requires an `llm` argument at construction — it's the only built-in tool with a mandatory dependency
- Sub-agent calls do NOT inherit the parent agent's tool registry — pass tools explicitly via the `task` description if needed
- For more sophisticated sub-agent patterns, use full nested `Agent` instances and call `agent.run()` from a custom tool's `run()` method

---

## Reasoning helper combinations

These tools work especially well in sequence:

```
decompose_problem  →  web_search + open_url  →  synthesize_evidence  →  decision_matrix  →  verify_output
     ↓                       ↓                          ↓                    ↓                  ↓
  workstreams           raw evidence              structured facts         recommendation     final check
```

A research agent can chain all five in a single `agent.run()` call, with each tool building on the previous one's output.

---

## Next: [Code & files →](code-and-files.md)
