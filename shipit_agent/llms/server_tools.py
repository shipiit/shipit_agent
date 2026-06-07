"""Constructor helpers for Anthropic **server-side tools** and document
citations (the "power passthrough" features added in v1.0.12).

Server-side tools run inside Anthropic's own sandbox — the model invokes them,
Anthropic executes them, and the results come back inline in the response. No
local infrastructure or client-side tool loop is involved. To use them you just
declare them in the ``tools`` list you pass to :meth:`AnthropicChatLLM.complete`
(mixed freely with ordinary client-side tools); the adapter forwards any dict
that already carries a ``"type"`` key as-is and attaches the right beta headers.

Every ``type`` string and the beta-header values below were verified against
the installed ``anthropic`` 0.79.0 SDK:

* ``anthropic.types.web_search_tool_20250305_param``  → ``web_search_20250305``
* ``anthropic.types.beta.beta_code_execution_tool_20250522_param``
  → ``code_execution_20250522`` (beta: ``code-execution-2025-05-22``)
* ``anthropic.types.beta.beta_tool_computer_use_20250124_param``
  → ``computer_20250124`` (beta: ``computer-use-2025-01-24``)
* ``anthropic.types.tool_bash_20250124_param`` → ``bash_20250124``
* ``anthropic.types.tool_text_editor_20250728_param``
  → ``text_editor_20250728`` / name ``str_replace_based_edit_tool``

The ``BETA_HEADERS`` map records which declarations require a ``betas`` /
``anthropic-beta`` header; the adapter consults it when assembling a request.
``web_search`` is generally-available and needs no beta header, so it is absent
from the map on purpose.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Verified Anthropic identifiers (anthropic SDK 0.79.0)
# ---------------------------------------------------------------------------
WEB_SEARCH_TYPE = "web_search_20250305"
CODE_EXECUTION_TYPE = "code_execution_20250522"
COMPUTER_USE_TYPE = "computer_20250124"
BASH_TYPE = "bash_20250124"
TEXT_EDITOR_TYPE = "text_editor_20250728"

# Beta header strings (verified in anthropic.types.anthropic_beta_param).
CODE_EXECUTION_BETA = "code-execution-2025-05-22"
COMPUTER_USE_BETA = "computer-use-2025-01-24"

# Map a server-tool ``type`` -> the beta header it requires. Tools not listed
# here (e.g. web_search, which is GA) need no beta header.
BETA_HEADERS: dict[str, str] = {
    CODE_EXECUTION_TYPE: CODE_EXECUTION_BETA,
    COMPUTER_USE_TYPE: COMPUTER_USE_BETA,
}

# Response block ``type`` strings produced by server-side tool use. The adapter
# parses these into response metadata instead of running them locally.
SERVER_TOOL_USE_BLOCK = "server_tool_use"
SERVER_TOOL_RESULT_BLOCKS = (
    "web_search_tool_result",
    "code_execution_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
)


def is_server_tool(tool: dict[str, Any]) -> bool:
    """True if ``tool`` is a server-side tool declaration (has a ``type``).

    Client-side tools follow the OpenAI ``{"function": {...}}`` / flat shape and
    never carry a top-level ``type``; server-side tools always do. The adapter
    uses this to decide whether to translate the schema or forward it as-is.
    """
    return isinstance(tool, dict) and "type" in tool


def required_betas(tools: list[dict[str, Any]] | None) -> list[str]:
    """Return the beta-header strings required by the server tools in ``tools``.

    Order-stable and de-duplicated. Empty when ``tools`` has no server tools
    that need a beta header (so the adapter can stay on the GA endpoint).
    """
    betas: list[str] = []
    for tool in tools or []:
        if not is_server_tool(tool):
            continue
        beta = BETA_HEADERS.get(str(tool.get("type", "")))
        if beta and beta not in betas:
            betas.append(beta)
    return betas


# ---------------------------------------------------------------------------
# Server-tool constructor helpers
# ---------------------------------------------------------------------------
def web_search(max_uses: int = 5, **extra: Any) -> dict[str, Any]:
    """Anthropic hosted **web search** tool (``web_search_20250305``).

    The model issues searches in Anthropic's sandbox and the results stream back
    inline. ``max_uses`` caps the number of searches per request. Extra keys
    (e.g. ``allowed_domains``, ``blocked_domains``, ``user_location``) are
    forwarded verbatim.
    """
    tool: dict[str, Any] = {
        "type": WEB_SEARCH_TYPE,
        "name": "web_search",
        "max_uses": max_uses,
    }
    tool.update(extra)
    return tool


def code_execution(**extra: Any) -> dict[str, Any]:
    """Anthropic hosted **code execution** tool (``code_execution_20250522``).

    Requires the ``code-execution-2025-05-22`` beta header, which the adapter
    attaches automatically when this tool is present.
    """
    tool: dict[str, Any] = {
        "type": CODE_EXECUTION_TYPE,
        "name": "code_execution",
    }
    tool.update(extra)
    return tool


def computer_use(
    display_width_px: int,
    display_height_px: int,
    *,
    display_number: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Anthropic **computer use** tool (``computer_20250124``).

    Requires the ``computer-use-2025-01-24`` beta header (attached
    automatically). ``display_width_px`` / ``display_height_px`` are required by
    the SDK type; ``display_number`` is optional.
    """
    tool: dict[str, Any] = {
        "type": COMPUTER_USE_TYPE,
        "name": "computer",
        "display_width_px": display_width_px,
        "display_height_px": display_height_px,
    }
    if display_number is not None:
        tool["display_number"] = display_number
    tool.update(extra)
    return tool


def bash(**extra: Any) -> dict[str, Any]:
    """Anthropic **bash** tool (``bash_20250124``)."""
    tool: dict[str, Any] = {
        "type": BASH_TYPE,
        "name": "bash",
    }
    tool.update(extra)
    return tool


def text_editor(**extra: Any) -> dict[str, Any]:
    """Anthropic **text editor** tool (``text_editor_20250728``).

    The SDK requires the tool ``name`` to be ``str_replace_based_edit_tool`` for
    this type string.
    """
    tool: dict[str, Any] = {
        "type": TEXT_EDITOR_TYPE,
        "name": "str_replace_based_edit_tool",
    }
    tool.update(extra)
    return tool
