# Agents as tools

An agent can be handed to another agent as a tool. A researcher, a
reviewer and a writer become three callables a coordinating agent picks
between by description — the same way it picks between `read_file` and
`web_search`.

```python
from shipit_agent import Agent, AgentTool

researcher = Agent(llm=cheap_llm, tools=[web_search, open_url])
reviewer = Agent(llm=good_llm, tools=[read_file, grep_files])

lead = Agent(llm=good_llm, tools=[
    AgentTool(researcher,
              name="researcher",
              description="Finds and reads sources on the web"),
    AgentTool(reviewer,
              name="reviewer",
              description="Reads the codebase and critiques a change"),
])

lead.run("Is our retry logic in line with current best practice?")
```

The lead reaches for `researcher` to find what current practice is, then
`reviewer` to compare it with what the code does, then answers. You wrote
no routing logic: the descriptions are the routing.

## When this, and when `sub_agent`

They look similar and are not interchangeable.

| | `sub_agent` | `AgentTool` |
|---|---|---|
| The child is | built from the parent | one **you** configured |
| Its model is | the parent's | whatever you gave it |
| Its tools are | the parent's, read-only | whatever you gave it |
| You choose when | the policy decides | you decide, by adding the tool |

Use `sub_agent` to split work the parent already knows how to do — four
files, four children, one join. Use `AgentTool` when the child should be
*different*: a cheaper model for a wide search, a specialist prompt, a
narrower toolbox, or a session that persists across calls.

## Descriptions are the interface

The description is the only thing the calling model sees. It is not
documentation, it is the routing rule.

```python
# Vague — the lead cannot tell when this applies.
AgentTool(agent, name="helper", description="Helps with things")

# Specific — names the work, and implies when NOT to call it.
AgentTool(agent, name="sql_analyst",
          description="Answers questions about the warehouse by writing "
                      "and running SQL. Use for numbers, not for prose.")
```

## A durable child session

Pass `session_id` and the child keeps its own thread across calls, so a
specialist consulted twice in one run remembers the first consultation.

```python
AgentTool(reviewer, name="reviewer", description="…",
          session_id="review-thread")
```

Without it, every call starts the child fresh — which is usually what you
want, and is why it is the default.

## What the parent sees

Nested events surface through the parent's stream, so a delegated run
reads as work rather than as a pause:

```python
for event in lead.stream("Is our retry logic current?"):
    if event.type == "sub_agent_event":
        print(" ", event.payload["agent"], event.payload["inner"]["tool"])
```

Set `stream_events=False` if you would rather the child ran quietly and
only its answer came back.

## Failure and depth

Two behaviours worth knowing, both of which exist because the obvious
implementation gets them wrong.

**A child that fails does not end the parent's turn.** Its exception comes
back as a tool result the model can act on, so the parent can say so, try
another route, or answer without it:

```python
result = lead.run("Is our retry logic current?")
# researcher could not complete the task: the provider is down
```

**Delegation cannot recurse forever.** An agent holding a tool that wraps
an agent holding the same tool would recurse until something ran out.
`AgentTool` shares the depth counter with `sub_agent` — one counter, so
the two cannot disagree — and refuses past two levels, naming the
alternative rather than only saying no.

## See also

- [Deep agents](deep-agents.md) — delegation the policy decides for you
- [Scheduled agents](scheduled-agents.md) — each job with its own stack
- [Skills](skills.md) — giving a specialist its instructions
