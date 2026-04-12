# Launch announcement kit

Copy-paste-ready blurbs for announcing **shipit-agent** on each platform. Each one is tuned to the platform's culture, length limits, and norms — you shouldn't need to rewrite them, just personalize the author line at the bottom.

**Core facts** (edit these if you ship a new version):

- **Package:** `shipit-agent`
- **PyPI:** https://pypi.org/project/shipit-agent/
- **Docs:** https://docs.shipiit.com/
- **GitHub:** https://github.com/shipiit/shipit_agent
- **License:** MIT
- **Python:** ≥3.11

---

## 🟠 Hacker News — "Show HN"

**Title:** `Show HN: Shipit-agent – Python agent runtime with live reasoning events`

**Body:**

```
Hi HN, I built shipit-agent because I kept hitting the same problems with
existing agent frameworks:

1. Streaming events arrived all at once at the end instead of incrementally
2. AWS Bedrock tool loops crashed on the third iteration due to tool_use/
   tool_result pairing bugs
3. Switching LLM providers meant rewriting half my app
4. Reasoning/thinking blocks from o1, Claude, and gpt-oss were silently
   dropped by the framework

Shipit-agent fixes all of these:

- agent.stream() runs the agent on a background thread and yields events
  through a queue as they happen. No buffering, no "waits until done then
  dumps everything"
- Reasoning content from any provider (OpenAI reasoning_content, Anthropic
  thinking_blocks, Bedrock gpt-oss, DeepSeek R1) is extracted automatically
  and emitted as reasoning_started / reasoning_completed events, so your UI
  can render a live "Thinking" panel for free
- The runtime guarantees every toolUse block gets a paired toolResult —
  even when the model hallucinates an unregistered tool name (it gets a
  synthetic error result) and when the built-in planner runs (its output is
  injected as a user-role context message, not an orphan tool-result).
  Bedrock multi-iteration tool loops finally work
- Set SHIPIT_LLM_PROVIDER in .env to switch between OpenAI, Anthropic,
  Bedrock, Gemini, Vertex AI, Groq, Together, Ollama, or a self-hosted
  LiteLLM proxy. One line, no code change
- In-process Playwright for open_url (no external scraper services)
- Semantic tool_search so agents don't hallucinate tool names when you
  have 28+ tools attached
- 14 structured event types documented, WebSocket/SSE packet transports,
  file-backed session/memory/trace stores, native MCP integration

Zero mandatory dependencies in the core. Every LLM SDK is an optional
extra. 91 tests, MIT licensed, docs at docs.shipiit.com

  pip install shipit-agent

Feedback welcome, especially from people who've been burned by agent
frameworks that over-abstract the runtime loop.
```

---

## 🔵 Reddit r/Python — Show-off post

**Title:** `[Show] shipit-agent — a Python agent runtime with live reasoning events, Bedrock tool-pairing guarantees, and zero-dep streaming`

**Flair:** `Showcase`

**Body:**

```markdown
Hey r/Python! I'm excited to share **shipit-agent**, a clean, powerful Python agent library I've been building to solve the specific problems I kept running into with other agent frameworks.

## What problems does it solve?

After building production agents with several other libraries, these kept biting me:

- 🐢 **Streaming that wasn't actually streaming** — events buffered up and arrived at the end
- 💥 **Bedrock tool loops crashing** on the 3rd iteration with "toolResult blocks exceed toolUse blocks" errors
- 🔀 **Provider lock-in** — switching from OpenAI to Bedrock meant rewriting half the app
- 🧠 **Reasoning/thinking blocks dropped** — o1, Claude extended thinking, and Bedrock gpt-oss all surfacing reasoning, but the framework silently discarding it

## What shipit-agent does about it

### 🧠 Live reasoning events
Extracted from OpenAI o-series, Claude extended thinking, Bedrock gpt-oss, and DeepSeek R1 via a single `_extract_reasoning()` helper shared by all three adapters. Emitted as `reasoning_started` / `reasoning_completed` events before each tool call. Your UI can render a live "Thinking" panel for free.

### ⚡ Truly incremental streaming
`agent.stream()` runs the agent on a background thread and pushes events through a `queue.Queue` as they're emitted. Works in Jupyter, VS Code, WebSocket, SSE, and plain terminals. No buffering.

### 🛡️ Bulletproof Bedrock tool pairing
Every `toolUse` block gets a matched `toolResult`. Planner output is injected as user context, not orphan tool-results. Hallucinated tool names get synthetic error results. Multi-iteration loops just work.

### 🔑 Zero-friction provider switching
```python
# .env
SHIPIT_LLM_PROVIDER=openai    # or anthropic, bedrock, gemini, vertex, groq, together, ollama
OPENAI_API_KEY=sk-...
```

Nine providers supported, including self-hosted LiteLLM proxy servers and Vertex AI with service-account JSON file support.

### 🌐 In-process Playwright for `open_url`
Headless Chromium in-process. No external scraper services. Stdlib urllib fallback if Playwright isn't installed. Zero third-party HTTP dependencies in the core fallback path.

### 🔍 Semantic tool discovery
`ToolSearchTool` uses fuzzy scoring (`SequenceMatcher + token hits`) to rank 28+ tools by relevance. Prevents tool hallucination and token bloat.

## Install

```bash
pip install shipit-agent
```

## 30-second example

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(llm=OpenAIChatLLM(model="o3-mini"))

for event in agent.stream("Find today's Bitcoin price from two sources and compare."):
    print(event.type, event.message)
```

## Links

- 📦 PyPI: https://pypi.org/project/shipit-agent/
- 📖 Docs: https://docs.shipiit.com/
- 💻 GitHub: https://github.com/shipiit/shipit_agent

MIT license, Python 3.11+, 91 tests, full docs, CI-guarded. Feedback and bug reports welcome!
```

---

## 🐦 X / Twitter — thread

**Tweet 1/8** (hook):

```
Just shipped shipit-agent v1.0 to PyPI 🚀

A clean Python agent runtime that finally gets streaming right:

🧠 Live reasoning events from o1/Claude/gpt-oss
⚡ Truly incremental streaming (no buffering!)
🛡️ Bedrock tool pairing that actually works

pip install shipit-agent

Thread 👇
```

**Tweet 2/8** (reasoning events):

```
2/ The problem: o1, o3, Claude extended thinking, and Bedrock gpt-oss all
emit reasoning blocks. Most frameworks drop them on the floor.

shipit-agent extracts them automatically and emits them as events:

reasoning_started  🧠 iteration 1
reasoning_completed 🧠 "I'll start with web_search..."

Your UI gets a "Thinking" panel for free.
```

**Tweet 3/8** (incremental streaming):

```
3/ The problem: `for event in agent.stream(...)` in most frameworks
gives you all events at once at the end. Not actually streaming.

shipit-agent runs the agent on a background thread and pushes events
through a queue as they happen. Each event reaches your loop the instant
it's emitted.
```

**Tweet 4/8** (Bedrock):

```
4/ The problem: AWS Bedrock's Converse API enforces strict 1:1 pairing
between tool_use blocks and tool_result blocks. Most frameworks mess this
up on the 3rd iteration and crash.

shipit-agent guarantees every tool_use gets a matched tool_result — even
when the model hallucinates unknown tool names. No more crashes.
```

**Tweet 5/8** (providers):

```
5/ Switching providers is one line in .env:

SHIPIT_LLM_PROVIDER=openai   # or anthropic/bedrock/gemini/vertex/groq/
                             # together/ollama/litellm-proxy

No code changes. Same agent, different model. Every adapter supports
the same reasoning extraction and tool-pairing guarantees.
```

**Tweet 6/8** (tool_search):

```
6/ Got 28 tools attached? The model will hallucinate names and waste
tokens on schemas it'll never use.

ToolSearchTool ranks all available tools by fuzzy-match score:

tool_search(query="fetch a specific URL")
→ 1. open_url (0.42)
   2. playwright_browser (0.31)
   3. web_search (0.19)
```

**Tweet 7/8** (stack):

```
7/ Built clean:

🎯 Zero mandatory deps in core
🐍 Python 3.11+
🧪 91 tests, CI-guarded
🔒 Gitleaks secret scanning
📖 Full MkDocs Material docs
📦 MIT license
🏗️ Protocol-based extensibility

The runtime is small enough to extend without fighting framework overhead.
```

**Tweet 8/8** (CTAs):

```
8/ Everything you need:

📦 pip install shipit-agent
📖 Docs: docs.shipiit.com
💻 Code: github.com/shipiit/shipit_agent
📋 PyPI: pypi.org/project/shipit-agent

Feedback welcome — especially from folks who've been burned by
over-abstracted agent frameworks.

#Python #LLM #AgenticAI #OpenSource
```

---

## 💼 LinkedIn

```markdown
🚀 Shipped v1.0 of shipit-agent — a Python agent runtime I've been building to fix the specific problems I kept hitting with other agent frameworks.

Three problems that kept biting me:

1️⃣ **Streaming events that weren't actually streaming** — events buffered up and arrived at the end, so live "Thinking" panels were impossible

2️⃣ **AWS Bedrock tool loops crashing** on the third iteration with "toolResult blocks exceed toolUse blocks" pairing errors

3️⃣ **Reasoning/thinking blocks dropped** — OpenAI o-series, Claude extended thinking, and Bedrock gpt-oss all surface reasoning content, but frameworks silently discarded it

**shipit-agent** fixes all of these:

→ Runs agents on a background thread with a thread-safe event queue, so `agent.stream()` yields events the instant they're emitted
→ Guarantees every toolUse block gets a matched toolResult, even when the model hallucinates unregistered tool names (synthetic error results) and when the planner runs (output becomes user context, not an orphan result)
→ Extracts reasoning content from any provider via a shared helper — no configuration, no opt-in
→ Nine LLM providers supported out of the box (OpenAI, Anthropic, Bedrock, Gemini, Vertex AI, Groq, Together, Ollama, LiteLLM proxy)
→ In-process Playwright for URL fetching with stdlib urllib fallback
→ Semantic tool search so agents with 28+ tools don't hallucinate names

Built clean with zero mandatory dependencies in the core, 91 tests, CI-guarded, MIT licensed, and a full MkDocs Material documentation site.

**Install:**
```
pip install shipit-agent
```

📦 PyPI: https://pypi.org/project/shipit-agent/
📖 Docs: https://docs.shipiit.com/
💻 GitHub: https://github.com/shipiit/shipit_agent

Feedback welcome — especially if you've hit any of the same pain points I described above.

#Python #OpenSource #LLM #AI #AgenticAI
```

---

## 💬 Python Discord — #show-your-work

```
Hey everyone! Just shipped v1.0 of **shipit-agent** 🚀

It's a clean Python agent runtime I built because I kept hitting the same issues with other agent frameworks:
- 🐢 Streaming events that buffered up and arrived at the end
- 💥 Bedrock tool loops crashing on iteration 3
- 🧠 Reasoning/thinking blocks silently dropped
- 🔀 Can't switch LLM providers without rewriting half the app

**Highlights:**
- 🧠 Live reasoning events from o1/o3/gpt-5/Claude/gpt-oss — for a live "Thinking" panel UI
- ⚡ Background-thread streaming via `queue.Queue` — events yield instantly as emitted
- 🛡️ Bulletproof Bedrock tool pairing — multi-iteration loops just work
- 🔑 9 providers via `SHIPIT_LLM_PROVIDER` env var
- 🌐 In-process Playwright for `open_url`, no external scrapers
- 🔍 Semantic `tool_search` so agents don't hallucinate tool names

Zero mandatory deps, 91 tests, MIT, Python 3.11+, full MkDocs Material docs.

```bash
pip install shipit-agent
```

📦 https://pypi.org/project/shipit-agent/
📖 https://docs.shipiit.com/
💻 https://github.com/shipiit/shipit_agent

Any feedback welcome, especially on the DX of the streaming API!
```

---

## 📧 Python Weekly / PyCoder's Weekly submission

Both newsletters accept submissions via web forms. Keep your blurb under 500 chars for best inclusion rates.

**Subject:** `New library: shipit-agent — Python agent runtime with live reasoning events`

**Body:**

```
shipit-agent is a clean Python agent library with live reasoning events
(from o1/Claude/gpt-oss), truly incremental streaming via a background
thread + queue, bulletproof AWS Bedrock tool_use/tool_result pairing, and
zero-friction provider switching via .env (9 providers: OpenAI, Anthropic,
Bedrock, Gemini, Vertex AI, Groq, Together, Ollama, LiteLLM proxy).

Also ships in-process Playwright for open_url, semantic tool_search, file-
backed session/memory/trace stores, and native MCP integration.

Zero mandatory deps, 91 tests, MIT, Python 3.11+.

Install: pip install shipit-agent
PyPI:    https://pypi.org/project/shipit-agent/
Docs:    https://docs.shipiit.com/
GitHub:  https://github.com/shipiit/shipit_agent
```

**Submit at:**
- Python Weekly: https://www.pythonweekly.com/
- PyCoder's Weekly: https://pycoders.com/

---

## 📝 Blog post / Dev.to / Medium

Write a longer-form version with:

1. **The problem** — concrete pain points you hit before building this
2. **The solution** — how shipit-agent addresses each
3. **Code samples** — `agent.stream()`, reasoning events, tool_search
4. **Architecture** — brief tour of runtime.py, the background-thread pattern, the pairing invariants
5. **Benchmarks** — (optional) startup time, memory footprint, streaming latency
6. **Lessons learned** — the planner-injection bug you fixed, the Bedrock pairing insight
7. **Call to action** — install, star, feedback

Target length: 1500-2500 words. Include at least one screenshot of the Jupyter notebook showing live streaming events.

**Good publishing homes:**
- Dev.to (#python, #opensource, #ai)
- Medium (Python tag)
- Your own blog with canonical link
- Hashnode (#python, #llm)

---

## 📜 Awesome lists (GitHub PR)

Open PRs to add shipit-agent to these lists. Follow each list's contribution guidelines.

| List | URL | Section |
|---|---|---|
| **awesome-python** | https://github.com/vinta/awesome-python | `Machine Learning` or `AI Agents` |
| **awesome-llm** | https://github.com/Hannibal046/Awesome-LLM | `LLM Agent Frameworks` |
| **awesome-ai-agents** | https://github.com/e2b-dev/awesome-ai-agents | `Python agent frameworks` |
| **awesome-mcp** | https://github.com/punkpeye/awesome-mcp-servers | `MCP clients` |
| **Python Trending** | https://github.com/trending/python | Automatic — no PR needed |

**Standard PR format:**

```markdown
- [shipit-agent](https://github.com/shipiit/shipit_agent) - A clean Python agent runtime with live reasoning events, incremental streaming, Bedrock tool-pairing guarantees, and 9-provider support via .env. MIT.
```

---

## 📊 Track the launch

Tools to watch your launch metrics:

- **PyPI downloads:** https://pypistats.org/packages/shipit-agent
- **GitHub stars over time:** https://star-history.com/#shipiit/shipit_agent
- **HN discussion:** https://news.ycombinator.com/from?site=github.com/shipiit (after posting)
- **Reddit engagement:** reddit.com/r/Python + your post URL

Expect a launch-day bump, then a tail. Sustained growth comes from docs quality, issue responsiveness, and the package actually solving real problems — which yours does.

---

## Launch-day checklist

Before you post anywhere:

- [ ] `pip install shipit-agent` works in a fresh venv
- [ ] Docs site is live at https://docs.shipiit.com/
- [ ] README PyPI badges render correctly (green)
- [ ] v1.0.1 git tag exists and GitHub release page is published
- [ ] CHANGELOG.md is current
- [ ] No open critical bugs (or at least an issue acknowledging them)
- [ ] `gitleaks` and `test` CI workflows show green on main
- [ ] At least 3 example notebooks that run cleanly end-to-end

All 8 items ✅ → you're good to announce.

---

Copy the platform-specific section, personalize the author line, and post. You've built something genuinely useful — tell the world. 🚀
