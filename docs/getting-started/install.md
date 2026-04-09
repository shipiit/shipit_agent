# Installation

SHIPIT Agent requires **Python 3.11 or newer**.

## From PyPI

```bash
pip install shipit-agent
```

## With optional extras

SHIPIT Agent keeps its core dependency footprint at **zero**. LLM provider SDKs and browser tooling are opt-in:

| Extra | Installs | Needed for |
|---|---|---|
| `[openai]` | `openai>=1.30.0` | `OpenAIChatLLM` adapter (native SDK, supports o-series reasoning) |
| `[anthropic]` | `anthropic>=0.34.0` | `AnthropicChatLLM` adapter (native thinking blocks) |
| `[litellm]` | `litellm>=1.42.0` | Bedrock, Gemini, Groq, Together, Ollama, any LiteLLM-backed provider |
| `[playwright]` | `playwright>=1.45.0` | In-process browser for `open_url` and `web_search`'s Playwright provider |
| `[dev]` | `pytest>=8.0.0` | Running the test suite |
| `[all]` | All of the above | Everything |

```bash
pip install 'shipit-agent[openai]'
pip install 'shipit-agent[anthropic]'
pip install 'shipit-agent[litellm]'
pip install 'shipit-agent[playwright]'
pip install 'shipit-agent[all]'
```

## Playwright browser binaries

If you install the `playwright` extra, you also need to download the Chromium binary once:

```bash
playwright install chromium
```

Without this, `open_url` silently falls back to `urllib` (works for static pages, fails on JS-heavy targets like CoinDesk or anti-bot CDNs).

## From source

```bash
git clone https://github.com/shipiit/shipit_agent.git
cd shipit_agent
pip install -e '.[dev]'
```

## Verify

```python
import shipit_agent
from shipit_agent import Agent, ToolSearchTool

print(shipit_agent.__version__)   # 1.0.0
print(Agent)                       # <class 'shipit_agent.agent.Agent'>
```

## Next

- [Quick start](quickstart.md) — build your first agent in five minutes
- [Environment setup](environment.md) — configure `.env` for provider switching
