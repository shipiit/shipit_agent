"""Small, factual helpers used to narrate runtime progress."""

from __future__ import annotations

from typing import Any

from shipit_agent.models import ToolResult


def join_clauses(parts: list[str]) -> str:
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def arguments_by_name(tool_calls: list[Any] | None) -> dict[str, dict]:
    """Map calls by name without relying on result/call positional parity."""
    found: dict[str, dict] = {}
    for call in tool_calls or []:
        name = getattr(call, "name", "")
        if name and name not in found:
            found[name] = dict(getattr(call, "arguments", None) or {})
    return found


def bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


_SPOKEN_LIMIT = 400


def first_sentences(text: str | None) -> str:
    """Trim model prose at a sentence boundary for a glanceable update."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    stripped = " ".join(stripped.split())
    if len(stripped) <= _SPOKEN_LIMIT:
        return stripped
    cut = stripped[:_SPOKEN_LIMIT]
    for end in (". ", "! ", "? "):
        index = cut.rfind(end)
        if index > 40:
            return cut[: index + 1]
    return cut.rsplit(" ", 1)[0] + "…"


_NOT_PROSE = ('":', '"}', '{"', "//", "```", "<tool", "()")


def looks_like_prose(text: str) -> bool:
    """Reject broken serialized tool calls masquerading as model prose."""
    stripped = (text or "").strip()
    if len(stripped) < 4 or any(marker in stripped for marker in _NOT_PROSE):
        return False
    letters = sum(
        character.isalpha() or character.isspace() for character in stripped
    )
    return letters / len(stripped) >= 0.75


def describe_result(result: ToolResult) -> str:
    """Return only a summary explicitly supplied by the tool."""
    metadata = getattr(result, "metadata", None) or {}
    summary = metadata.get("summary")
    return str(summary).strip() if summary else ""


def result_failed(result: ToolResult) -> bool:
    metadata = result.metadata or {}
    return bool(metadata.get("error")) or metadata.get("ok") is False


# Preserve private runtime names while making the public helpers testable.
_join_clauses = join_clauses
_arguments_by_name = arguments_by_name
_bounded = bounded
_first_sentences = first_sentences
_looks_like_prose = looks_like_prose
_describe_result = describe_result
_result_failed = result_failed
