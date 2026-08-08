# Delegation

Some tasks are one thing. Some are eight things wearing a trench coat.
Delegation is the agent noticing the difference and splitting the second
kind across sub-agents that each hold their own context.

```python
from shipit_agent import Agent

agent = Agent(llm=llm, tools=tools, delegation=True)

agent.run("Read all 4 reports and summarise each one")
# → four children, four summaries, one join
```

That is the whole setup. `delegation=True` attaches a policy; the policy
decides.

## Why it is worth doing

Not speed — context. A sub-agent reads a long file and returns four
sentences, and only those four sentences enter the parent's context. The
file never does.

Without delegation, an agent that reads eight reports carries all eight in
its window for the rest of the run, and the last question you ask is
answered by a model that spent its budget remembering report three.

## When it fires, and when it does not

The policy judges each task, and the toolbox follows that judgement — an
agent working on a single-step task is not offered a sub-agent at all.

```python
# Separable: four named targets.
agent.run("Read a.py, b.py and c.py and summarise each")     # delegates

# Breadth: no number, but every item in a set.
agent.run("Go through every document attached")              # delegates

# One search.
agent.run("Look for the latest AI news")                     # does not
```

That last case is the one worth understanding. A model asked "could this
be split?" will say yes about almost anything — asked about "the latest AI
news" it will propose splitting by topic, by source, by date. None of
those appear in the request. So a model's yes has to be corroborated by
something actually in the text: an enumerated list, several named targets,
a stated quantity, or a distributive determiner over a noun.

If it is not, the task is one search, and three agents doing it is three
model calls to produce a worse answer than one.

## Tuning it

```python
from shipit_agent import DelegationPolicy

agent = Agent(llm=llm, tools=tools, delegation=DelegationPolicy(
    min_items=3,              # below this, do it yourself
    read_only_children=True,  # children may read, never write
    max_iterations=8,         # a child's budget
))
```

`read_only_children` defaults to `True` and should usually stay there. A
sub-agent that can write is a side effect nobody reviewed: the parent
delegated "summarise this" and got a file changed.

## Asking the policy directly

The assessment is available if you want to log it, or decide something
yourself:

```python
advice = agent._delegation_policy().assess(task, llm=agent.llm)
print(bool(advice), advice.items, advice.reasons, advice.source)
# True 4 ['4 concrete targets are named'] structural
```

`source` is `structural` when the text alone decided it and `model` when
the LLM was asked. `reasons` is what was noticed — it goes into the
directive the model receives, so the instruction says *why* rather than
nagging in the abstract.

## Background children

A child can run in the background while the parent keeps working:

```python
# Inside the agent's own tool calls:
sub_agent(task="…", background=True)     # returns a task id
sub_agent(collect="task-1")              # fetches the result
```

One rule matters: **anything started in the background must be collected
in the same turn.** The run ends when the agent writes its answer, and an
uncollected task is discarded. An agent that tells you it will "report
back with the results" is describing something that cannot happen.

## Delegation versus agents as tools

`delegation=True` builds children from the parent — same model, same
tools, read-only. Use it to split work the parent already knows how to do.

When the child should be *different* — a cheaper model, a specialist
prompt, its own toolbox — wrap a configured agent instead. See
[agents as tools](agents-as-tools.md).

## What a delegated run looks like

Children stream through the parent, so delegation is visible rather than a
gap:

```python
for event in agent.stream(task):
    if event.type == "sub_agent_event":
        inner = event.payload["inner"]
        print(event.payload["agent"], inner.get("tool"))
```

Only the child's *work* is forwarded, not its prose. The parent already
reports the conclusion, and streaming both says everything twice.

## See also

- [Agents as tools](agents-as-tools.md) — when the child should be different
- [Deep agents](deep-agents.md) — planning, critics and a research crew
- [Streaming](streaming.md) — the full event vocabulary
