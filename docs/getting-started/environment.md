# Environment Setup

SHIPIT Agent uses environment variables for provider selection, credentials, and runtime knobs. Everything loads automatically from a `.env` file walking upward from your current working directory — so the same notebook, script, or CLI works regardless of where you run it from.

## Minimal `.env`

```bash
SHIPIT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

## Full `.env.example`

```bash
# Core agent settings
SHIPIT_LLM_PROVIDER=bedrock           # or openai|anthropic|gemini|groq|together|ollama
SHIPIT_AGENT_PROMPT=You are a decisive engineering agent.
SHIPIT_STREAM=0
SHIPIT_SESSION_ID=demo-session
SHIPIT_TRACE_ID=demo-trace
SHIPIT_WORKSPACE_ROOT=.shipit_workspace

# Web search
SHIPIT_WEB_SEARCH_PROVIDER=duckduckgo
BRAVE_SEARCH_API_KEY=
SERPER_API_KEY=
TAVILY_API_KEY=

# OpenAI
SHIPIT_OPENAI_MODEL=gpt-4o-mini
SHIPIT_OPENAI_TOOL_CHOICE=            # "required" forces at least one tool call per turn
OPENAI_API_KEY=

# Anthropic
SHIPIT_ANTHROPIC_MODEL=claude-opus-4-1
ANTHROPIC_API_KEY=

# AWS Bedrock via LiteLLM
SHIPIT_BEDROCK_MODEL=bedrock/openai.gpt-oss-120b-1:0
AWS_REGION_NAME=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
AWS_PROFILE=

# Google Gemini
SHIPIT_GEMINI_MODEL=gemini/gemini-1.5-pro
GOOGLE_API_KEY=
```

## How `.env` is discovered

`build_llm_from_env()` walks upward from the current working directory looking for the first `.env` file it finds. That means:

| CWD | `.env` location | Works? |
|---|---|---|
| `/path/to/project/` | `/path/to/project/.env` | ✅ |
| `/path/to/project/notebooks/` | `/path/to/project/.env` | ✅ (walks up) |
| `/path/to/project/deep/nested/dir/` | `/path/to/project/.env` | ✅ (walks up) |
| `/tmp/scratch/` | (none) | ❌ — raises "Missing environment variable" |

Existing shell environment variables always take precedence over `.env` — `.env` only *fills in* missing values, it never overrides.

## Provider credential requirements

| Provider | Required env vars |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `bedrock` | `AWS_REGION_NAME` (or `AWS_DEFAULT_REGION`) + one of `AWS_ACCESS_KEY_ID`+`AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, or instance role |
| `gemini` | `GOOGLE_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `together` | `TOGETHER_API_KEY` |
| `ollama` | *None* (requires local Ollama server running) |

If any required var is missing, `build_llm_from_env('openai')` raises:

```
RuntimeError: Missing environment variable for openai. Set one of: OPENAI_API_KEY
```

## Switching providers without restarting

```python
from examples.run_multi_tool_agent import build_llm_from_env

# Explicit override (ignores SHIPIT_LLM_PROVIDER):
llm_openai = build_llm_from_env('openai')
llm_bedrock = build_llm_from_env('bedrock')

# Uses SHIPIT_LLM_PROVIDER from .env:
llm = build_llm_from_env()
```

## Security notes

- **Never commit `.env`.** The shipped `.gitignore` already excludes `.env`, `.env.local`, and `.env.*.local`.
- **Use `.env.example` as a template.** Commit it with all values blank so contributors know which vars to set.
- **The credential visibility printer in the sample notebooks never prints the actual value** — only `✓ set` / `✗ missing`. Safe to share.
- **API keys are never written to logs or events.** Adapters only report the provider name and model on `LLMResponse.metadata`.
