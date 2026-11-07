"""Each model's context window and output limit, and the budget compaction works to."""

from __future__ import annotations

from dataclasses import dataclass

# Compact once the prompt reaches this share of the input budget, leaving room
# for the response that turn still has to produce.
TRIGGER_RATIO = 0.75


# Retain roughly this share of the budget after compacting, leaving room for the
# summary and the turns that follow. Compacting to 85% would re-trigger at once.
TARGET_RATIO = 0.20


# A model we have no entry for. One whose real window is smaller will fail at
# the provider before this ever triggers, which is the safe direction.
DEFAULT_CONTEXT_WINDOW = 128_000


DEFAULT_MAX_OUTPUT = 8_192


# ``(context_window, max_output_tokens)``. Prefix-matched, so dated snapshots
# (``claude-opus-4-20250514``) and vendor-prefixed ids
# (``us.anthropic.claude-…``) resolve without an entry each.
MODEL_CONTEXT_WINDOWS: dict[str, tuple[int, int]] = {
    "claude-opus-5": (1_000_000, 64_000),
    "claude-sonnet-5": (1_000_000, 64_000),
    "claude-fable-5": (200_000, 64_000),
    "claude-opus-4": (200_000, 32_000),
    "claude-sonnet-4": (200_000, 64_000),
    "claude-haiku-4": (200_000, 32_000),
    "claude-3-5-sonnet": (200_000, 8_192),
    "claude-3-5-haiku": (200_000, 8_192),
    "gpt-5": (400_000, 128_000),
    "gpt-4.1": (1_047_576, 32_768),
    "gpt-4o": (128_000, 16_384),
    "o3": (200_000, 100_000),
    "o4-mini": (200_000, 100_000),
    "gemini-2.5-pro": (1_048_576, 65_536),
    "gemini-2.5-flash": (1_048_576, 65_536),
    "gemini-1.5-pro": (2_097_152, 8_192),
    "llama-3.3": (128_000, 8_192),
    "mistral-large": (128_000, 8_192),
    "gemma-3": (128_000, 8_192),
    # Gemma 4 31B / 26B-A4B are 256K windows; E2B is 128K. The more specific
    # e2b key wins by longest-prefix match. Without these, a 256K model was
    # compacted at an eighth of its capacity — the likely cause of "it forgets".
    "gemma-4-e2b": (128_000, 8_192),
    "gemma-4": (256_000, 16_384),
    "gpt-oss": (128_000, 32_768),
}


@dataclass(frozen=True, slots=True)
class ModelLimits:
    """How a model's context window divides between prompt and response."""

    context_window: int
    max_output_tokens: int

    @property
    def input_budget(self) -> int:
        """What the prompt may use — the window minus reserved response room."""
        return max(1, self.context_window - self.max_output_tokens)


def get_model_limits(model: str | None) -> ModelLimits:
    """Limits for *model*, by longest-prefix match, with a safe default."""
    if not model:
        return ModelLimits(DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_OUTPUT)
    from shipit_agent.llms.claude_models import STREAMING_OUTPUT_CAP, known_claude_model

    claude = known_claude_model(model)
    if claude is not None:
        # One source for Claude limits. Reserve what a call actually asks for
        # (the streamed default), not the model's full output ceiling.
        return ModelLimits(
            claude.context_window, min(claude.max_output_tokens, STREAMING_OUTPUT_CAP)
        )

    def _match(name: str) -> tuple[int, int] | None:
        """Longest-prefix match against the table."""
        best: tuple[int, tuple[int, int]] | None = None
        for key, value in MODEL_CONTEXT_WINDOWS.items():
            if name.startswith(key) and (best is None or len(key) > best[0]):
                best = (len(key), value)
        return best[1] if best else None

    normalized = str(model).lower()
    # Try the id as given FIRST. Model names legitimately contain dots
    # (`gemini-2.5-pro`, `gpt-4.1`), so eagerly splitting on "." would turn
    # `gemini-2.5-pro` into `5-pro` and lose the match entirely.
    found = _match(normalized)
    if found:
        return ModelLimits(*found)

    # Only then peel vendor routing prefixes one segment at a time —
    # `us.anthropic.claude-opus-5`, `anthropic/claude-sonnet-4`.
    remainder = normalized
    while True:
        cut = min(
            (remainder.index(sep) for sep in ("/", ".") if sep in remainder),
            default=-1,
        )
        if cut < 0:
            break
        remainder = remainder[cut + 1 :]
        found = _match(remainder)
        if found:
            return ModelLimits(*found)

    return ModelLimits(DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_OUTPUT)
