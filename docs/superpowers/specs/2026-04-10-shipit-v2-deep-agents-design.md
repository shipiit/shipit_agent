# SHIPIT Agent v2 — Deep Agents Design Spec

**Date:** 2026-04-10
**Status:** Approved
**Goal:** Make SHIPIT the most powerful open-source agent framework — everything LangChain has plus deep agent capabilities LangChain doesn't.

## Modules

### 1. Structured Output (`shipit_agent/structured.py`)
- `output_schema` parameter on `Agent.run()` and `AgentResult.parsed`
- Supports Pydantic models (returns validated instance) and raw JSON schema dicts
- Auto-retry on parse failure with error feedback to LLM

### 2. Output Parsers (`shipit_agent/parsers/`)
- `OutputParser` protocol with `parse(text) -> Any`
- `JSONParser`, `PydanticParser`, `RegexParser`, `MarkdownParser`

### 3. Pipeline (`shipit_agent/pipeline/`)
- `Pipeline.sequential()` and `parallel()` for deterministic composition
- `step()` with template references `{step_name.output}`
- Conditional routing via `router` lambdas
- Steps can be agents, plain functions, or conditional branches

### 4. Agent Teams (`shipit_agent/team/`)
- `AgentTeam` with LLM coordinator that routes work dynamically
- `TeamAgent` with name, role, and agent instance
- Shared memory, round history, streaming, max_rounds safety

### 5. Advanced Memory (`shipit_agent/memory/`)
- `AgentMemory` unified interface with conversation + semantic + entity
- `ConversationMemory` with buffer/window/summary/token strategies
- `SemanticMemory` with embedding-based vector search
- `EntityMemory` for tracking people/projects/concepts
- `VectorStore` protocol with InMemory implementation
- `AgentMemory.default(llm)` smart defaults

### 6. Deep Agents (`shipit_agent/deep/`)
- `GoalAgent` — autonomous goal decomposition with success criteria tracking
- `ReflectiveAgent` — self-evaluation and revision loop
- `AdaptiveAgent` — creates new tools at runtime
- `Supervisor` / `Worker` — hierarchical agent management
- `PersistentAgent` — checkpoint and resume across sessions
- `AgentMessage` / `Channel` — typed agent communication
- `AgentBenchmark` / `TestCase` — evaluation framework
