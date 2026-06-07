# shipit-agent 1.0.12 — Claude API power + cross-provider caching

Adds the high-leverage Claude API features — **server-side tools**,
**citations**, the **Batch API**, **interleaved thinking** and server-side
**context editing** — and, importantly, makes **prompt caching work across
providers**, not just Anthropic.

> All opt-in and backward compatible. `pip install -U shipit-agent`.

**1844 tests passing (+49 new) · 0 regressions · ruff clean.**

---

## ⚡ Cross-provider prompt caching

Caching is no longer Anthropic-only:

| Provider | How | Surfaced |
| --- | --- | --- |
| Anthropic / Bedrock / Vertex | explicit `cache_control` breakpoints (default on for Claude) | `cache_read_input_tokens`, `cache_creation_input_tokens` |
| **OpenAI / OpenAI-compatible** | **automatic** prompt caching (no config) | now surfaces `cache_read_input_tokens` from `prompt_tokens_details.cached_tokens` |
| LiteLLM | forwards both shapes | both |

`CostTracker` reads the same keys for every provider, so cache reads bill at the
discounted rate regardless of which LLM you use. The OpenAI adapter also passes
through `reasoning_tokens` for reasoning models.

## 🌐 Server-side tools (Anthropic)

```python
from shipit_agent.llms import AnthropicChatLLM, web_search, code_execution
```

`web_search()`, `code_execution()`, `computer_use()`, `bash()`, `text_editor()`
declare tools that run in **Anthropic's sandbox** — zero local infrastructure.
The adapter forwards them, attaches the required beta headers automatically, and
routes `server_tool_use`/result blocks into `LLMResponse.metadata`.

> These are Anthropic API shapes. On **other providers**, use shipit's
> client-side tools (`WebSearchTool`, `CodeExecutionTool`, `VisionTool`, …) —
> they already work with any LLM.

## 📑 Citations & 📦 Batch API

- **Citations** — `text_document()` / `pdf_document()` / `url_pdf_document()`
  attach documents with `citations.enabled`; response citations land in
  `metadata["citations"]` for verifiable RAG.
- **`BatchRuntime`** (`shipit_agent.batch`) — submit many requests to the
  Anthropic Messages Batches API for **~50%-cheaper** bulk runs;
  `run(requests)` polls to completion with an injectable clock for testing.

## 🧠 Interleaved thinking & context editing

`AnthropicChatLLM(interleaved_thinking=True, thinking_budget_tokens=2048)` adds
the interleaved-thinking beta and surfaces thinking blocks; `context_management=`
forwards Anthropic's server-side context editing.

---

## Provider support, honestly

shipit-agent supports **OpenAI, Anthropic, Bedrock, Vertex, Gemini, Groq,
Together, Ollama, and LiteLLM**. Prompt caching now spans Anthropic + OpenAI +
their proxies. The server-tools / citations / interleaved-thinking passthroughs
are Anthropic API shapes — every other provider has its own native equivalent,
and shipit's **client-side** tools and per-provider reasoning controls already
work everywhere. Each notebook and docs page states its provider support
explicitly.

## 📒 Examples & docs

- Notebooks `64_server_side_tools`, `65_citations_and_batch`,
  `66_interleaved_thinking` (all execute offline).
- Docs pages for each feature + an updated cross-provider caching matrix.

---

Full diff: <https://github.com/shipiit/shipit_agent/compare/v1.0.11...v1.0.12>
