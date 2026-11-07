"""Assembling the prompt so its prefix is byte-stable across a conversation.

Implicit prompt caching on ``bedrock-mantle`` is automatic and needs no markers.
What it needs is a prefix that does not move: consecutive requests sharing a
common prefix can reuse cached internal state, and cached input tokens are
cheaper *and* do not count against the input-token quota. So prefix stability is
not a micro-optimisation — it is throughput.

The failure is easy to reach by accident. Four things routinely shift a prefix
between iterations of the same run:

1. History rewriting to repair tool-call pairing, which inserts turns.
2. Skill bodies appended into the system prompt when a skill is selected.
3. A rules block rebuilt from live state on every call.
4. Tool definitions serialised in whatever order a dict happened to iterate.

The last one is the quietest and the cheapest to fix: sorting tool definitions
by name costs one line and recovers every cache hit that gating, MCP discovery
order or deferred loading was silently destroying.

This module owns the layout and nothing else. It renders once per run, hands
back an immutable :class:`PromptPrefix`, and exposes a fingerprint so a test can
assert the prefix did not move across iterations. Volatile content — skill
bodies, plans, the conversation — belongs in the tail and is deliberately not
representable here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "PromptPrefix",
    "SkillCatalogEntry",
    "build_prefix",
    "sort_tool_definitions",
    "fingerprint",
]


def _tool_name(definition: Mapping[str, Any]) -> str:
    """Name of an OpenAI-style tool entry, or of a bare schema."""
    function = definition.get("function")
    if isinstance(function, Mapping):
        return str(function.get("name", ""))
    return str(definition.get("name", ""))


def sort_tool_definitions(
    definitions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministic tool order.

    Tool sets are assembled from several sources — builtins, plugins, MCP
    discovery, skill-widened sets — and none of them guarantee a stable
    iteration order between calls. Sorting by name makes the serialised block
    identical whenever the *set* is identical, which is the condition implicit
    caching actually tests.
    """
    return sorted((dict(d) for d in definitions), key=_tool_name)


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    """One catalog line: enough to choose a skill, not enough to use it."""

    id: str
    name: str
    description: str

    def render(self, *, max_description_chars: int = 120) -> str:
        summary = " ".join(self.description.split())
        if len(summary) > max_description_chars:
            summary = summary[: max_description_chars - 1].rstrip() + "…"
        return f"- {self.id} — {self.name}: {summary}" if summary else f"- {self.id} — {self.name}"


@dataclass(frozen=True, slots=True)
class PromptPrefix:
    """The stable head of a prompt, rendered once per run.

    ``system_text`` is what goes in the system slot; ``tool_definitions`` is the
    sorted tool block. Both are frozen: mutating either mid-run is exactly the
    bug this class exists to prevent.
    """

    system_text: str
    tool_definitions: tuple[dict[str, Any], ...] = ()
    sections: Mapping[str, str] = field(default_factory=dict)

    @property
    def tools(self) -> list[dict[str, Any]]:
        """A mutable copy, for handing to an SDK that wants a list."""
        return [dict(d) for d in self.tool_definitions]

    def fingerprint(self) -> str:
        """Stable hash of everything a provider would see as the prefix."""
        payload = json.dumps(
            {
                "system": self.system_text,
                "tools": list(self.tool_definitions),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def approx_tokens(self, counter: Any = None) -> int:
        """Rough size of the prefix, for budget accounting."""
        text = self.system_text + json.dumps(
            list(self.tool_definitions), sort_keys=True, default=str
        )
        if counter is not None:
            try:
                return int(counter(text))
            except Exception:  # noqa: BLE001
                pass
        return max(1, len(text) // 4)


def _section(title: str, body: str) -> str:
    body = body.strip()
    return f"## {title}\n{body}" if body else ""


def build_prefix(
    *,
    system_prompt: str,
    rules: str = "",
    mcp_instructions: Mapping[str, str] | None = None,
    skill_catalog: Sequence[SkillCatalogEntry] = (),
    tool_definitions: Iterable[Mapping[str, Any]] = (),
    max_catalog_entries: int = 200,
    max_description_chars: int = 120,
) -> PromptPrefix:
    """Render the stable prefix in a fixed order.

    The order is the contract::

        1. system prompt (base — never skill bodies)
        2. rules block (rendered once, not rebuilt per call)
        3. MCP server instructions (deduped, sorted by server)
        4. skill catalog (names + one-line descriptions, sorted, capped)
        5. tool definitions (sorted by name)

    Everything volatile — primed skill bodies, the plan, the conversation —
    goes in the tail and is not accepted here. Sorting the MCP block and the
    catalog matters as much as sorting tools: server discovery order and
    registry iteration order are both incidental.
    """
    parts: list[str] = [system_prompt.strip()]
    sections: dict[str, str] = {}

    if rules.strip():
        sections["rules"] = rules.strip()
        parts.append(_section("Rules", rules))

    if mcp_instructions:
        # Deduped by server name and sorted, so two runs that attached the same
        # servers in different orders produce the same bytes.
        lines = [
            f"### {server}\n{text.strip()}"
            for server, text in sorted(mcp_instructions.items())
            if text and text.strip()
        ]
        if lines:
            body = "\n\n".join(lines)
            sections["mcp_instructions"] = body
            parts.append(_section("Connected server instructions", body))

    if skill_catalog:
        entries = sorted(skill_catalog, key=lambda e: e.id)[:max_catalog_entries]
        body = "\n".join(
            entry.render(max_description_chars=max_description_chars)
            for entry in entries
        )
        listing = (
            "Skills available on demand. Each line is a name and a summary — "
            "the full instructions are not loaded yet. Call `load_skill` with "
            "an id to load one when it is relevant to the task.\n\n" + body
        )
        sections["skill_catalog"] = listing
        parts.append(_section("Skills", listing))

    return PromptPrefix(
        system_text="\n\n".join(part for part in parts if part).strip(),
        tool_definitions=tuple(sort_tool_definitions(tool_definitions)),
        sections=sections,
    )


def fingerprint(prefix: PromptPrefix) -> str:
    """Module-level alias, for callers that hold the value not the object."""
    return prefix.fingerprint()
