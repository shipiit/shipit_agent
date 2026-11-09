---
title: Episodic Memory Consolidation
description: Distill long conversations into durable facts. Apply forgetting curves so old facts decay. Promote frequently-retrieved facts to a "core memory" set always visible to the agent. ChatGPT-style memory built into shipit.
---

# Episodic Memory Consolidation

Today, an agent restarted next week starts cold even if you kept its
session history. Plain RAG over old transcripts is high-noise. With
**consolidation**, the agent carries forward distilled facts — *"user
prefers brief answers"*, *"the auth service uses Argon2"*, *"Q3 release
deadline is Oct 14"* — that survive across sessions, decay gracefully
over time, and surface as core context every turn.

> **TL;DR** — `MemoryConsolidator(llm=cheap_llm).consolidate(memory=...,
> recent_messages=...)` distills a conversation into 3-8 facts, writes
> them to `SemanticMemory`, and you get ChatGPT-style "remembers things
> across sessions" for free.

---

## Three pieces of the system

| Method | What it does | Frequency |
| --- | --- | --- |
| `consolidate()` | LLM distills recent conversation → facts → writes to `SemanticMemory` | After every N turns or session close |
| `decay()`       | Pure-Python exponential decay of fact strength; prunes facts below threshold | Daily / weekly cron |
| `core_memory()` | Returns top-K facts ranked by `strength + retrievals` for the system prompt | Every agent turn |
| `record_retrieval()` | Bump retrieval counter for facts that were just returned by a search | After every successful `memory.search_knowledge(...)` |

All four operate on a `SemanticMemory` (or any compatible store).
Together they implement the cognitive-architecture pattern of
**episodic → semantic consolidation**.

---

## Quick start

```python
from shipit_agent import Agent
from shipit_agent.memory import (
    AgentMemory, MemoryConsolidator, SemanticMemory, InMemoryVectorStore,
)

# Build memory
memory = AgentMemory(
    knowledge=SemanticMemory(vector_store=InMemoryVectorStore()),
)

# Consolidator — typically a cheap LLM (Haiku, gpt-oss-20b)
consolidator = MemoryConsolidator(
    llm=cheap_llm,
    max_facts_per_pass=8,
    min_messages=6,
    confidence_threshold=0.5,
)

# Build an agent that uses the memory
agent = Agent(llm=opus_llm)

# After a few turns, consolidate
result = consolidator.consolidate(
    memory=memory,
    recent_messages=memory.conversation.get_messages(),
)

for fact in result.facts:
    print(f"[{fact.category}] {fact.text} ({fact.confidence:.2f})")
```

Output:

```
[preference] User wants concise answers, no preamble
[project]    Auth service uses Argon2 with 12-byte salt
[goal]       Q3 release deadline is Oct 14
[person]     Alice owns the deploy pipeline
```

---

## Decay (forgetting curve)

Run periodically — ideally daily. Pure local arithmetic, no LLM call.

```python
# Half-life of 14 days: a 14-day-old fact decays to strength 0.5,
# 28-day-old to 0.25, etc. Facts whose strength falls below
# `forgetting_threshold` (default 0.1) are pruned.

pruned = consolidator.decay(memory.knowledge, half_life_days=14)
print(f"pruned {pruned} stale facts")
```

The decay curve is exponential:

```
strength_new = strength_old × exp(-ln(2) × elapsed_days / half_life_days)
```

| Age | Strength @ 14-day half-life |
| --- | --- |
| 1 day | 0.95 |
| 7 days | 0.71 |
| 14 days | 0.50 |
| 28 days | 0.25 |
| 60 days | 0.05 (pruned) |

You can disable pruning (`prune=False`) to keep stale facts but lower
their strength — useful if you want them retrievable but de-prioritised.

---

## Core memory (always-on context)

After each turn, get the top-K most-load-bearing facts and prepend them
to the system prompt:

```python
core_facts = consolidator.core_memory(
    memory.knowledge,
    top_k=5,
    min_retrievals=0,   # set ≥1 to require some past retrieval before promoting
)

system_prompt_addition = "\n".join(f"- {f}" for f in core_facts)

agent = Agent(
    llm=opus_llm,
    prompt=BASE_PROMPT + "\n\nKnown facts about this user/project:\n" + system_prompt_addition,
)
```

Ranking is `strength + 0.1 × log1p(retrievals)`. Facts with high
strength rise; facts that were retrieved often rise faster. Frequently
useful facts naturally float to the top.

---

## Record retrievals (close the feedback loop)

When you do `memory.search_knowledge(query)` and get useful results,
tell the consolidator so it can bump those facts' retrieval counters:

```python
results = memory.search_knowledge("Argon2", top_k=3)
consolidator.record_retrieval(
    memory.knowledge,
    [r.text for r in results],
)
```

Why bother? Because `core_memory()` uses retrievals as a popularity
signal. Facts you keep retrieving become core memory; facts that gather
dust just decay away. The system gets smarter about *what to remember*
over time.

---

## Full lifecycle in your agent loop

A complete pattern that hooks all four methods together:

```python
class MemoryEnabledAgent:
    def __init__(self, llm, cheap_llm):
        self.memory = AgentMemory.default(llm=llm)
        self.consolidator = MemoryConsolidator(llm=cheap_llm)
        self.turn_count = 0

    def chat(self, user_message: str) -> str:
        # 1. Inject core facts into prompt
        core = self.consolidator.core_memory(self.memory.knowledge, top_k=5)
        agent = Agent(
            llm=opus_llm,
            prompt=BASE_PROMPT + "\n\nKnown facts:\n" + "\n".join(f"- {f}" for f in core),
        )

        # 2. Run the turn
        result = agent.run(user_message)

        # 3. Update conversation memory
        from shipit_agent.models import Message
        self.memory.add_message(Message(role="user", content=user_message))
        self.memory.add_message(Message(role="assistant", content=result.output))
        self.turn_count += 1

        # 4. Every 10 turns, consolidate
        if self.turn_count % 10 == 0:
            self.consolidator.consolidate(
                memory=self.memory,
                recent_messages=self.memory.get_conversation_messages(),
            )

        # 5. Once per day in your real app: decay + prune
        # self.consolidator.decay(self.memory.knowledge, half_life_days=14)

        return result.output
```

---

## Tuning

```python
MemoryConsolidator(
    llm=cheap_llm,                # any object with .complete(messages=...)
    max_facts_per_pass=8,         # cap on facts written per consolidation
    min_messages=6,               # don't consolidate short chats
    confidence_threshold=0.5,     # drop low-confidence facts
    forgetting_threshold=0.1,     # below this strength → pruned in decay()
)
```

| Setting | Lower means | Higher means |
| --- | --- | --- |
| `max_facts_per_pass` | Memory stays sparse | Memory grows fast (more LLM cost) |
| `min_messages` | Frequent consolidation | Consolidation only on long chats |
| `confidence_threshold` | More facts kept (some noise) | Fewer facts kept (more selective) |
| `forgetting_threshold` | Aggressive pruning | Long memory tail kept |

**Production defaults are good** — they map well to a Haiku-tier
verifier consolidating a daily personal-assistant agent.

---

## Cost analysis

Per consolidation pass:
* **Input** — last 30 messages × ~150 tokens = **~4.5K tokens**
* **Output** — 8 facts × ~30 tokens + JSON envelope = **~300 tokens**
* **Total** — ~5K tokens per pass.

On Haiku ($0.25 / $1.25 per Mtok), **~$0.0015 per consolidation**. Run
once every 10 turns: roughly $0.0015 / 10 turns = $0.00015 per turn
overhead.

`decay()` and `core_memory()` are pure local arithmetic — zero LLM cost.

---

## Why this beats ChatGPT-style "memories"

ChatGPT's Memories feature is essentially `add_fact(text)` with no
decay, no retrieval-based promotion, and no consolidation pass —
manual user input only. Ours:

| Capability | ChatGPT Memories | shipit consolidation |
| --- | --- | --- |
| Auto-extract from conversations | ❌ | ✅ |
| Forgetting curve | ❌ (manual delete only) | ✅ exponential |
| Retrieval-based promotion | ❌ | ✅ |
| Self-host with your own LLM | ❌ | ✅ |
| Fact categories | ❌ | ✅ (`preference`, `project`, `goal`, `person`) |
| Per-fact strength score | ❌ (binary on/off) | ✅ continuous 0..1 |

Same idea. More principled implementation. **You can run it on
production data without leaking it to anyone.**

---

## API reference

### `MemoryConsolidator`
```text
MemoryConsolidator(
    *, llm,
    max_facts_per_pass: int = 8,
    min_messages: int = 6,
    confidence_threshold: float = 0.5,
    forgetting_threshold: float = 0.1,
)
```

| Method | Returns | Notes |
| --- | --- | --- |
| `consolidate(*, memory, recent_messages)` | `ConsolidationResult` | LLM distillation + writes to memory.knowledge |
| `decay(knowledge, *, half_life_days, prune=True)` | `int` (pruned count) | Pure local arithmetic |
| `core_memory(knowledge, *, top_k=5, min_retrievals=0)` | `list[str]` | Ranked top-K facts |
| `record_retrieval(knowledge, fact_texts)` | `int` (bumped count) | Update retrieval popularity |

### `DistilledFact`
| Field | Type | Default |
| --- | --- | --- |
| `text` | `str` | — |
| `category` | `str` | `"other"` |
| `confidence` | `float` | `1.0` |
| `timestamp` | `float` | `time.time()` |
| `strength` | `float` | `1.0` (decays) |
| `retrievals` | `int` | `0` (incremented by `record_retrieval`) |

### `ConsolidationResult`
| Field | Description |
| --- | --- |
| `facts` | List of `DistilledFact` written this pass |
| `raw_text` | Verifier's raw JSON output (debugging) |
| `skipped_reason` | `None` on success; otherwise why we didn't run |

---

## Going deeper

* [Agent → Memory](./memory.md) — the underlying `AgentMemory`,
  `ConversationMemory`, `SemanticMemory`, `EntityMemory`
* [RAG → Overview](../rag/index.md) — bigger-scale persistent
  knowledge bases (whole document corpora)
* [Sessions & Memory](./sessions.md) — durable conversation
  state across process restarts
