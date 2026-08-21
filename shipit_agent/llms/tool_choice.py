"""One place that decides the provider `tool_choice` value.

Every OpenAI-shaped adapter (LiteLLM, the OpenAI/Bedrock-Mantle shim) was
duplicating the same ladder: force an exact function when exactly one tool is
eligible, fall back to ``"required"`` for several, otherwise pass a configured
choice or ``"auto"``. Consolidating it here means the Gemma-critical
"single tool → name it explicitly" rule (which stops a weak model narrating the
call instead of emitting it) has exactly one definition to keep correct.

The Anthropic adapter speaks a different dialect (``{"type": "any"}`` /
``{"type": "tool", "name": …}``) and keeps its own small mapping.
"""

from __future__ import annotations

from typing import Any


def resolve_tool_choice(
    tools: list[dict[str, Any]] | None,
    *,
    require_tool_call: bool = False,
    configured: str | dict[str, Any] | None = None,
    default_auto: bool = False,
) -> str | dict[str, Any] | None:
    """Return the ``tool_choice`` to send, or ``None`` to omit it.

    - No tools → ``None`` (the parameter is invalid without a tool list).
    - ``require_tool_call`` with exactly one eligible tool → an exact function
      choice ``{"type": "function", "function": {"name": …}}``; this is the
      rule that makes weak models emit the call instead of narrating it.
    - ``require_tool_call`` with several tools → ``"required"``.
    - Otherwise a caller-``configured`` choice if set, else ``"auto"`` when
      ``default_auto`` (some endpoints only engage function calling when the
      parameter is present), else ``None``.
    """
    if not tools:
        return None
    if require_tool_call:
        if len(tools) == 1:
            name = str((tools[0].get("function") or {}).get("name", ""))
            if name:
                return {"type": "function", "function": {"name": name}}
        return "required"
    if configured:
        return configured
    if default_auto:
        return "auto"
    return None
