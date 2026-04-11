# DeepAgent

`shipit_agent.deep.DeepAgent` is the power-user factory for building
agents that succeed at long, multi-step tasks. It bundles seven
purpose-built deep tools, an opinionated system prompt, and one-flag
access to verification, reflection, goal-driven mode, sub-agent
delegation, and a built-in interactive chat REPL — all behind the same
constructor your existing `Agent` code already understands.

> **TL;DR** — `DeepAgent.with_builtins(llm=llm).run(prompt)` gives
> you a ready-to-use deep agent. Add `rag=`, `verify=True`,
> `reflect=True`, `goal=Goal(...)`, or `agents=[…]` as one-keyword
> upgrades.

---

## What you get out of the box

Every `DeepAgent` ships with:

- **Seven deep tools** — `plan_task`, `decompose_problem`,
  `workspace_files`, `sub_agent`, `synthesize_evidence`,
  `decision_matrix`, `verify_output`
- **Opinionated `DEEP_AGENT_PROMPT`** that teaches the model to plan,
  verify, and manage context
- **A `chat()` helper** that returns an `AgentChatSession` for live
  multi-turn conversation
- **Streaming events** for every execution mode
- **First-class flags** for RAG, verification, reflection, goal-driven
  runs, and sub-agent delegation

`DeepAgent.with_builtins(...)` additionally bundles the regular
built-in tool catalogue (web search, code execution, file workspace,
integrations).

---

## Quick start

```python
from shipit_agent.deep import DeepAgent

agent = DeepAgent.with_builtins(llm=my_llm)
result = agent.run("Investigate the auth bug and propose a fix.")
print(result.output)
```

That gives you the seven deep tools, the full built-in tool catalogue,
and the opinionated `DEEP_AGENT_PROMPT`.

---

## Power-user mode

```python
from shipit_agent import AgentMemory
from shipit_agent.deep import DeepAgent

agent = DeepAgent.with_builtins(
    llm=my_llm,
    rag=my_rag,                  # auto-cited grounded answers
    verify=True,                  # run verifier after every answer
    reflect=True,                 # self-critique loop
    memory=AgentMemory.default(   # long-term memory
        llm=my_llm, embedding_fn=embed,
    ),
    max_iterations=20,            # deeper reasoning loops
    parallel_tool_execution=True,
    context_window_tokens=200_000,
)
```

---

## Run modes

`DeepAgent.run()` picks the execution mode automatically based on the
flags you set:

| Mode | Trigger | Behaviour |
| --- | --- | --- |
| Direct | default | Standard `Agent.run()` |
| Verified | `verify=True` | Standard run, then `verify_output` against criteria; verdict attached to `result.metadata["verification"]` |
| Reflective | `reflect=True` | Generate, critique, revise until `reflect_threshold` |
| Goal-driven | `goal=Goal(...)` | Decompose, execute, self-evaluate against criteria |

```python
from shipit_agent.deep import DeepAgent, Goal

agent = DeepAgent.with_builtins(
    llm=my_llm,
    goal=Goal(
        objective="Ship the auth fix",
        success_criteria=["Patch compiles", "Tests pass", "Migration is reversible"],
    ),
)
result = agent.run()              # decomposed, executed, evaluated
print(result.goal_status)         # "completed" | "partial" | "failed"
print(result.criteria_met)        # [True, True, True]
```

---

## Memory — `memory=` and `memory_store=`

`DeepAgent` exposes two independent memory parameters:

| Parameter | Type | Owner | What it stores |
| --- | --- | --- | --- |
| `memory_store=` | `MemoryStore` | the LLM (via the runtime's `memory` tool) | timestamped `MemoryFact`s the LLM decides to remember |
| `memory=` | `AgentMemory` | your application code | conversation summary + semantic facts + entities you curate explicitly |

These are **two different stores with different interfaces** — they
don't share storage, but they coexist freely.

### `memory=` — application-curated context

When you pass `memory=AgentMemory(...)`, `DeepAgent` hydrates the
inner `Agent.history` from `memory.get_conversation_messages()` so a
fresh deep agent picks up where the prior conversation left off.

```python
from shipit_agent import AgentMemory
from shipit_agent.deep import DeepAgent

profile = AgentMemory.default(llm=llm, embedding_fn=embed)
profile.add_fact("user_allergy=gluten")
profile.add_fact("user_timezone=Europe/Berlin")

agent = DeepAgent.with_builtins(
    llm=llm,
    memory=profile,        # ← seeds inner Agent.history with summary
    rag=my_rag,
    verify=True,
)
result = agent.run("Suggest a restaurant near me for next Tuesday at 10am.")
```

### `memory_store=` — LLM-writable runtime memory

`memory_store=` is the backing store for the runtime's built-in
`memory` tool. The LLM can call `memory(action="add", ...)` and
`memory(action="search", ...)` during a run.

```python
from shipit_agent.deep import DeepAgent
from shipit_agent.stores import FileMemoryStore

agent = DeepAgent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),
)
```

### Combine both for the OpenAI-style pattern

```python
from shipit_agent import AgentMemory
from shipit_agent.deep import DeepAgent
from shipit_agent.stores import FileMemoryStore, FileSessionStore

profile = AgentMemory.default(llm=llm, embedding_fn=embed)

agent = DeepAgent.with_builtins(
    llm=llm,
    memory=profile,                                            # curated profile
    memory_store=FileMemoryStore(root="~/.shipit/memory"),     # LLM-writable
    session_store=FileSessionStore(root="~/.shipit/sessions"), # chat history
    rag=my_rag,
    verify=True,
)

chat = agent.chat(session_id="user-42")
chat.send("Remember that I'm allergic to gluten.")
profile.add_fact("user_allergy=gluten")    # mirror into your DB-backed profile
```

> The full memory cookbook lives at
> [Agent → Memory](../agent/memory.md). Everything there applies to
> `DeepAgent` too — the only difference is that `memory=` also seeds
> the inner agent's `history` automatically.

---

## Sub-agents — the `agents=` parameter

`DeepAgent` and `create_deep_agent` accept an `agents=` parameter that
lets you plug in named specialists the deep agent can delegate to. When
you set this, the deep agent gains a `delegate_to_agent` tool that the
model can call to hand off well-scoped sub-tasks while still using its
own deep toolset to plan, take notes, and verify the result.

```python
from shipit_agent import Agent
from shipit_agent.deep import DeepAgent

researcher = Agent.with_builtins(llm=llm, name="researcher",
                                 description="Searches docs and the web.")
writer     = Agent.with_builtins(llm=llm, name="writer",
                                 description="Drafts user-facing copy.")
reviewer   = Agent.with_builtins(llm=llm, name="reviewer",
                                 description="Checks final output for accuracy.")

agent = DeepAgent.with_builtins(
    llm=llm,
    agents=[researcher, writer, reviewer],   # ← named specialists
    rag=my_rag,
    verify=True,
)

result = agent.run("Investigate the auth bug, draft a fix, then review it.")
```

Inside the run the LLM can choose between its own deep tools and the
named delegates:

```text
plan_task → workspace_files (write notes)
         → delegate_to_agent(agent_name="researcher", task="...")
         → delegate_to_agent(agent_name="writer", task="...")
         → delegate_to_agent(agent_name="reviewer", task="...")
         → verify_output → final answer
```

### `agents=` accepts a list or a dict

```python
# List form — names are derived from each agent's `.name` attribute.
DeepAgent(llm=llm, agents=[researcher, writer])

# Dict form — names are explicit. Useful when you want a custom label
# or you have agents with the same .name.
DeepAgent(llm=llm, agents={
    "research": researcher,
    "draft":    writer,
    "review":   reviewer,
})
```

### Inspect and mutate sub-agents at runtime

```python
agent.sub_agents          # → {"researcher": ..., "writer": ..., "reviewer": ...}
agent.delegation_tool     # → AgentDelegationTool instance (or None)

# Add a sub-agent live (after the deep agent was built)
agent.add_sub_agent("translator", Agent(llm=llm, name="translator"))
```

### Chained deep agents — sub-agents can themselves be DeepAgents

```python
inner_deep = DeepAgent.with_builtins(llm=llm, name="inner-research-deep", rag=my_rag)
outer = DeepAgent.with_builtins(llm=llm, agents={"research_deep": inner_deep})
```

The outer deep agent now has access to a fully-equipped inner deep
agent (with its own seven deep tools, RAG, verification, …) as a
single delegation target. Compose freely — there is no depth limit.

### Streaming sub-agent activity

When the parent calls `delegate_to_agent`, the tool internally uses the
inner agent's `stream()` method (when available) and packs every event
into the parent's `tool_completed.metadata['events']`. UIs that render
the parent's stream automatically get visibility into what the
sub-agent did:

```python
for event in agent.stream("Investigate, draft, review."):
    if event.type == "tool_completed" and event.message.startswith("delegate_to_agent"):
        sub_events = event.payload.get("metadata", {}).get("events", [])
        print(f"  ↳ sub-agent did {len(sub_events)} steps")
        for inner in sub_events:
            print(f"     · [{inner['type']}] {inner['message']}")
```

To disable nested event capture (for performance), turn it off on the
delegation tool:

```python
agent.delegation_tool.capture_events = False
```

---

## Streaming — every mode emits events

Every execution mode of `DeepAgent` produces a streamable event flow:

```python
for event in agent.stream("..."):
    print(f"[{event.type}] {event.message}")
```

### Mode-by-mode streaming behaviour

| Mode | Triggered by | What you'll see |
| --- | --- | --- |
| **Direct** | default | Standard events (`run_started`, `step_started`, `tool_called`, `tool_completed`, `run_completed`). |
| **Verified** | `verify=True` | All direct events, plus a final `run_completed` with `message="verification_completed"` carrying the verifier verdict. |
| **Reflective** | `reflect=True` | Events for every generate→critique→revise cycle. |
| **Goal-driven** | `goal=Goal(...)` | `planning_started`, `planning_completed`, per-sub-task `step_started`/`tool_completed`, final `run_completed`. |
| **With sub-agents** | `agents=[...]` | All of the above, plus nested sub-agent events inside `tool_completed.metadata['events']` whenever `delegate_to_agent` is invoked. |

### End-to-end streaming example

```python
from shipit_agent.deep import DeepAgent, Goal

agent = DeepAgent.with_builtins(
    llm=llm,
    rag=my_rag,
    verify=True,
    goal=Goal(
        objective="Summarise the release notes",
        success_criteria=["Mentions deep agents", "Mentions RAG"],
    ),
)

for event in agent.stream():
    if event.type == "planning_started":
        print("📋 planning…")
    elif event.type == "planning_completed":
        for sub in event.payload.get("subtasks", []):
            print(f"  · {sub}")
    elif event.type == "tool_called":
        print(f"▶ {event.message}")
    elif event.type == "rag_sources":
        for s in event.payload.get("sources", []):
            print(f"  📎 [{s['index']}] {s['source']}")
    elif event.type == "run_completed":
        if event.message == "verification_completed":
            print("✅ verification:", event.payload["verification"]["text"][:80])
        else:
            print("✓ done:", (event.payload.get("output") or "")[:120])
```

### Streaming a sub-agent through the parent

```python
researcher = Agent.with_builtins(llm=llm, name="researcher", rag=my_rag)
agent = DeepAgent.with_builtins(llm=llm, agents=[researcher])

for event in agent.stream("Find references to streaming events in the docs."):
    if event.type == "tool_called" and event.message == "delegate_to_agent":
        print("📤 delegating to sub-agent…")
    if event.type == "tool_completed":
        nested = event.payload.get("metadata", {}).get("events", [])
        if nested:
            print(f"  ↳ {len(nested)} sub-events captured:")
            for ev in nested:
                print(f"     · {ev['type']}: {ev['message'][:60]}")
```

---

## The `create_deep_agent` functional helper

`create_deep_agent` is the functional spelling of `DeepAgent` — same
factory, same flags, just a function-style API:

```python
from shipit_agent.deep import create_deep_agent

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

agent = create_deep_agent(
    tools=[get_weather],
    llm=my_llm,
    system_prompt="You are a helpful weather assistant.",
    verify=True,
    reflect=True,
    rag=my_rag,
)

result = agent.run("what is the weather in sf")
```

Plain Python functions are auto-wrapped as
`shipit_agent.tools.FunctionTool` instances; classes implementing the
`Tool` protocol are passed through untouched.

`create_deep_agent` also accepts `agents=[...]` so you can wire
specialised sub-agents in one call:

```python
from shipit_agent import Agent
from shipit_agent.deep import create_deep_agent

researcher = Agent.with_builtins(llm=llm, name="researcher")
reviewer   = Agent.with_builtins(llm=llm, name="reviewer")

agent = create_deep_agent(
    llm=llm,
    agents=[researcher, reviewer],
    use_builtins=True,
    verify=True,
)

# Streams every parent event AND every sub-agent event nested inside
# `tool_completed.metadata['events']`.
for event in agent.stream("Investigate and review the auth module"):
    print(f"[{event.type}] {event.message}")
```

---

## Live chat — `shipit chat`

`shipit chat` opens an interactive REPL with the deep agent. You can
index files mid-session, set goals on the fly, save and reload
conversations, and inspect tools and sources.

```bash
shipit chat                                          # default: DeepAgent
shipit chat --rag-file docs/manual.pdf
shipit chat --provider anthropic --session-dir ~/.shipit/sessions
shipit chat --reflect --verify
shipit chat --goal "Build a todo CLI"
```

The REPL ships with rich slash commands:

```text
/help                show all slash commands
/tools               list the agent's tools
/sources             show RAG sources from the last turn
/index <path>        index a file into the active RAG
/rag                 show RAG stats
/goal <objective>    set a goal
/reflect on|off      toggle reflective mode
/verify on|off       toggle verification mode
/history             print conversation history
/clear               clear conversation history
/save <path>         save the conversation as JSON
/load <path>         load a saved conversation
/reset               start a fresh session
/quiet               toggle event streaming
/info                show agent + session info
/exit, /quit         leave the chat
```

Example session:

```
╭───────────────────────────────────────────────────╮
│ Shipit Agent — interactive chat                   │
│ agent=deep  session=chat-7f3c9a02                 │
╰───────────────────────────────────────────────────╯
type /help for commands  ·  /exit to quit

you ▸ /index docs/manual.pdf
[chat] indexed 137 chunks from docs/manual.pdf

you ▸ How do I configure logging?
agent ▸ Configure logging via SHIPIT_LOG_LEVEL in your .env. [1]
  (1 RAG source(s) — /sources to see)

you ▸ /sources
1 RAG source(s):
  [1] docs/manual.pdf (chunk docs_manual.pdf::42)
      Set SHIPIT_LOG_LEVEL=debug for verbose tracing...
```

---

## Programmatic chat sessions

Outside the CLI, every `DeepAgent` exposes a `.chat()` helper that
returns an `AgentChatSession`:

```python
from shipit_agent.deep import DeepAgent

agent = DeepAgent.with_builtins(llm=my_llm, rag=my_rag)
chat = agent.chat(session_id="user-42")

# Streaming (live UI)
for event in chat.stream("Hi, where do auth tokens get validated?"):
    print(event.message)

# Or blocking
result = chat.send("Anything else I should know?")
print(result.output)

# Conversation history
for msg in chat.history():
    print(msg.role, msg.content[:80])
```

The session is backed by whatever `session_store` you pass to
`DeepAgent` (or to `chat()` directly). Use `FileSessionStore` to
persist conversations across processes:

```python
from shipit_agent.stores import FileSessionStore

agent = DeepAgent.with_builtins(
    llm=my_llm,
    session_store=FileSessionStore(root="~/.shipit/sessions"),
)
chat = agent.chat(session_id="user-42")
```

---

## File layout

```
shipit_agent/deep/deep_agent/
├── __init__.py        # public exports
├── prompt.py          # DEEP_AGENT_PROMPT
├── toolset.py         # deep_tool_set() + merge_tools()
├── verification.py    # verify_text() helper
├── delegation.py      # AgentDelegationTool (sub-agent delegation)
└── factory.py         # DeepAgent class + create_deep_agent
```

The implementation is intentionally split into focused modules — the
factory class itself stays under 500 lines and reads top-to-bottom
without jumping around helper files.

---

## See also

- [Parameters Reference](../reference/parameters.md#deepagent) — every
  constructor parameter
- [Super RAG](../rag/index.md) — `rag=` integration
- Notebook: `notebooks/25_deep_agent_chat.ipynb`
