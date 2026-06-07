# shipit-agent 1.0.13 — Computer-use + adapter fixes

A focused patch fixing two bugs that blocked the **computer-use agent on every
provider**. Both are backward compatible — no API changes.

> `pip install -U shipit-agent`

**1854 tests passing (+10 new) · 0 regressions · ruff clean.**

---

## 🖥️ Computer-use now works in Jupyter / asyncio

`PlaywrightBrowserSession` used Playwright's **sync** API, which refuses to run
inside an already-running asyncio event loop — so launching it from a notebook
cell raised:

> *It looks like you are using Playwright Sync API inside the asyncio loop.*

It now runs every Playwright call on a dedicated, **loop-free worker thread**.
The public API is unchanged (still synchronous), so the same code works in
scripts, notebooks, and async web frameworks:

```python
with PlaywrightBrowserSession.launch(headless=True) as browser:
    agent = ComputerUseAgent(llm=llm, browser=browser, goal="...")
    result = agent.run()
```

## 🔌 All LLM adapters accept dict messages

`ComputerUseAgent` (and any caller) builds plain `{"role", "content"}` dict
messages — sometimes with multimodal list content — but adapters accessed
`message.role` and crashed with `'dict' object has no attribute 'role'`. This is
now handled at the adapter layer, so **every provider** works:

- **LiteLLM family** (Bedrock, Gemini, Vertex, Groq, Together, Ollama) and
  **OpenAI** — serialize dict messages and translate the Anthropic-shape base64
  image block to a portable `image_url` block.
- **Anthropic** and **ShipitLLM** — coerce dicts via the new shared
  `coerce_message()` / `coerce_messages()` helpers in `shipit_agent.llms.base`.

Because the fix lives in the adapters, any component that passes dict messages
is fixed — not just computer-use.

---

## Note on Llama on Bedrock

If you hit *"Access to Meta Llama models is not allowed from unsupported
countries…"* or *"The provided model identifier is invalid"* — those are **AWS /
Meta access restrictions**, not shipit-agent errors. Llama 4 isn't offered on
Bedrock EU, and Meta's EULA geo-restricts Llama access. For Llama from a
restricted region, use a non-Bedrock host (Groq, OpenRouter via
`LiteLLMProxyChatLLM`, or local Ollama).

---

Full diff: <https://github.com/shipiit/shipit_agent/compare/v1.0.12...v1.0.13>
