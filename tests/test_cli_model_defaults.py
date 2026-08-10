"""One CLI, one answer to "which model is the default".

`shipit run --provider anthropic` and `shipit chat --provider anthropic`
kept separate tables and drifted two generations apart — run used
claude-sonnet-5 while chat used claude-3-5-sonnet-latest, with nothing on
screen to say which you had. The catalog is authoritative now; these
pin that.
"""

from __future__ import annotations

import pytest

from shipit_agent.chat_cli import PROVIDER_MODEL_ENV
from shipit_agent.cli.llm import DEFAULT_MODELS, MODEL_CATALOG


class TestTheDefaultsAgree:
    @pytest.mark.parametrize("provider", sorted(DEFAULT_MODELS))
    def test_chat_uses_the_catalog_default(self, provider: str) -> None:
        assert PROVIDER_MODEL_ENV[provider][1] == DEFAULT_MODELS[provider]

    @pytest.mark.parametrize("provider", sorted(DEFAULT_MODELS))
    def test_the_default_is_a_model_the_catalog_lists(self, provider: str) -> None:
        """A default nobody can find in `shipit models` is a typo waiting."""
        listed = [model for model, _ in MODEL_CATALOG[provider]]
        assert DEFAULT_MODELS[provider] in listed

    def test_claude_is_a_claude_5(self) -> None:
        assert DEFAULT_MODELS["anthropic"].startswith("claude-sonnet-5")

    def test_every_provider_still_has_an_env_override(self) -> None:
        """Overlaying the catalog must not drop a provider's env var."""
        for provider, (env_var, _default) in PROVIDER_MODEL_ENV.items():
            if provider == "litellm":
                continue
            assert env_var.startswith("SHIPIT_"), provider

    def test_providers_outside_the_catalog_keep_their_defaults(self) -> None:
        """The catalog covers four providers; the rest are untouched rather
        than blanked by the overlay."""
        assert PROVIDER_MODEL_ENV["groq"][1]
        assert PROVIDER_MODEL_ENV["gemini"][1]
