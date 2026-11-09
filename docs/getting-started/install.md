---
description: Install shipit-agent and the extras for your model provider and tools.
---

# Install

ShipIt Agent needs Python 3.11 or newer. Its only required dependency is `pydantic`; a model provider's SDK, a browser or a vector store is an extra you add when you need it.

```bash
pip install shipit-agent
```

## Add your model provider

Install the extra for the provider you use. Several can be installed together.

| Provider | Extra | Environment variables |
| :- | :- | :- |
| Anthropic | `shipit-agent[anthropic]` | `ANTHROPIC_API_KEY` |
| OpenAI | `shipit-agent[openai]` | `OPENAI_API_KEY` |
| AWS Bedrock | `shipit-agent[bedrock]` | `AWS_REGION_NAME` and AWS credentials |
| Google Gemini | `shipit-agent[google]` | `GOOGLE_API_KEY` |
| Groq | `shipit-agent[groq]` | `GROQ_API_KEY` |
| Together | `shipit-agent[together]` | `TOGETHER_API_KEY` |
| Ollama (local) | `shipit-agent[ollama]` | none |
| Anything LiteLLM supports | `shipit-agent[litellm]` | the provider's own |

```bash
pip install 'shipit-agent[anthropic]'
```

[Configure a model](environment.md) covers choosing the model and the full list of settings.

## Add tools and features

| Extra | What it adds |
| :- | :- |
| `playwright` | `playwright_browse`, a real browser. Run `playwright install chromium` once after installing. |
| `pdf` | The `pdf` tool. |
| `files` | `read_file` for Word, Excel, PowerPoint and web pages, converted to Markdown. |
| `sql` | The `sql` tool (SQLAlchemy). Install your database driver too. |
| `connectors` | The connector catalog (GitHub, Slack, Jira and others). |
| `tts`, `video` | `text_to_speech` and `video_generate`. |
| `rag` | Everything for [Super RAG](../rag/index.md): embedders, vector stores, extractors, rerankers. |
| `langsmith`, `otel` | Trace exporters. |
| `all` | Every provider, tool and RAG extra. |

## Check the install

```bash
python -c "import shipit_agent; print(shipit_agent.__version__)"
shipit --help
```

The package installs two commands: `shipit`, the agent CLI, and `shipit-chat`, an interactive chat.

## Next

Run your first agent in the [Quickstart](quickstart.md).
