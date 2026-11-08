---
description: Choose a model provider and model, from code or from environment variables.
---

# Configure a model

An agent needs a model adapter, its `llm`. You can build one in code or let shipit build it from environment variables.

## From a model name

The quickest way is a model name. The provider is read from it: `claude-*` uses Anthropic, `gpt-*`, `o1`, `o3`, `o4` and `chatgpt-*` use OpenAI, `bedrock/...` uses Bedrock, and anything else goes through LiteLLM.

```python
from shipit_agent.sdk import AgentOptions, query

options = AgentOptions(model="claude-sonnet-5-5")
```

With the `Agent` class, build the adapter from the environment, choosing the provider explicitly or leaving it to `SHIPIT_LLM_PROVIDER`:

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env("anthropic"))
```

## Environment variables

`build_llm_from_env()` reads `SHIPIT_LLM_PROVIDER`, the provider's model variable and its credentials. It also loads the first `.env` file it finds walking up from the working directory. Variables already set in the shell win over the file.

| Provider | `SHIPIT_LLM_PROVIDER` | Model variable (default) | Credentials |
| :- | :- | :- | :- |
| Anthropic | `anthropic` | `SHIPIT_ANTHROPIC_MODEL` (`claude-opus-5-5`) | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `SHIPIT_OPENAI_MODEL` (`gpt-5.5`) | `OPENAI_API_KEY` |
| AWS Bedrock | `bedrock` | `SHIPIT_BEDROCK_MODEL` (`bedrock/openai.gpt-oss-120b-1:0`) | `AWS_REGION_NAME` plus keys, a profile or a role |
| Google Gemini | `gemini` | `SHIPIT_GEMINI_MODEL` (`gemini/gemini-3.5-flash`) | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| Vertex AI | `vertex` | `SHIPIT_VERTEX_MODEL` (`vertex_ai/gemini-3.5-flash`) | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| Groq | `groq` | `SHIPIT_GROQ_MODEL` | `GROQ_API_KEY` |
| Together | `together` | `SHIPIT_TOGETHER_MODEL` | `TOGETHER_API_KEY` |
| Ollama | `ollama` | `SHIPIT_OLLAMA_MODEL` (`ollama/llama3.1`) | none; a local Ollama server |
| LiteLLM | `litellm` | `SHIPIT_LITELLM_MODEL` | the provider's own |

When `SHIPIT_LLM_PROVIDER` is unset, the provider is `bedrock`.

A minimal `.env`:

```bash
SHIPIT_LLM_PROVIDER=anthropic
SHIPIT_ANTHROPIC_MODEL=claude-sonnet-5-5
ANTHROPIC_API_KEY=sk-ant-...
```

If a credential is missing, building the adapter raises and names the variable to set. If the provider's package is missing, it raises with the `pip install` command. shipit never answers with a different provider than the one you chose.

## Picking a model

Any model that supports tool calling works. Two measured points from the [benchmark](../guides/benchmark.md), running all 18 tasks:

| Model | Passed | Input tokens | Cost |
| :- | -: | -: | -: |
| Gemma 4 31B on Bedrock | 18/18 | 216k | $0.03 |
| Claude Sonnet 5.5 | 18/18 | 190k | $0.20 |

Strong models finish in fewer turns; small open models cost less per run. Run the benchmark against your own candidates before choosing.

## Keep keys out of code

- Never commit `.env`. Commit a `.env.example` with the names and no values.
- shipit does not write keys to logs, events or traces. Adapters report only the provider and model.
- Commands the agent runs get a scrubbed environment: host secrets are not visible to `printenv`. Pass the variables a tool needs with `AgentOptions(env={...})`.
