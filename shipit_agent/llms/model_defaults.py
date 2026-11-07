"""The model each provider uses when the caller names none.

One table, used by the adapters, the settings factory and the CLI. The
provider catalog's ``default_model`` values must match it (a test enforces
that), so a retired model cannot survive in one copy after it is replaced in
another.

Only providers whose flagship ids are stable enough to pin appear here.
Others ship no default and ask for ``SHIPIT_<PROVIDER>_MODEL``. Checked
against each provider's model and deprecation pages in November 2026.
"""

from __future__ import annotations

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5.5",
    "gemini": "gemini/gemini-3.5-flash",
    "vertex": "vertex_ai/gemini-3.5-flash",
    "groq": "groq/llama-3.3-70b-versatile",
    "together": "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
    "ollama": "ollama/llama3.1",
    "mistral": "mistral/mistral-large-latest",
    "deepseek": "deepseek/deepseek-chat",
    "perplexity": "perplexity/sonar",
}
