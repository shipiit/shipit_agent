"""Registered verbs, and the summary and counts every label is built from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .humanize import _humanize
from .spec import VerbSpec, pluralize
from .table import VERBS
from .targets import _SUMMARY_OVERRIDES, _extract_target

_OVERRIDES: dict[str, VerbSpec] = {}


def register_verb(name: str, spec: VerbSpec) -> None:
    """Teach the Narrator how one tool narrates itself.

    Overrides the built-in table, so this works both for tools shipit has
    never heard of and for changing how a built-in reads::

        from shipit_agent.narrate import VerbSpec, register_verb

        register_verb(
            "deploy_service",
            VerbSpec("Deployed", "Deploying", "✚", noun="service",
                     args=("service", "name")),
        )

    Without a registration, an unknown tool still narrates — the humanizing
    fallback turns ``deploy_service`` into *Deployed service* — so this is for
    when you want better than the guess, not to avoid a crash.
    """
    if not isinstance(spec, VerbSpec):
        raise TypeError(f"expected VerbSpec, got {type(spec).__name__}")
    _OVERRIDES[name] = spec


def register_verbs(specs: dict[str, VerbSpec]) -> None:
    """Register several at once — see :func:`register_verb`."""
    for name, spec in (specs or {}).items():
        register_verb(name, spec)


def unregister_verb(name: str) -> None:
    """Drop a registration, restoring the built-in (or the fallback)."""
    _OVERRIDES.pop(name, None)


def registered_verbs() -> dict[str, VerbSpec]:
    """The currently registered overrides (a copy)."""
    return dict(_OVERRIDES)


def spec_for(name: str) -> VerbSpec:
    """The :class:`VerbSpec` for *name*.

    Resolution order: caller registrations, then the built-in table, then the
    humanizing fallback.
    """
    return _OVERRIDES.get(name) or VERBS.get(name) or _humanize(name)


def icon_for(name: str) -> str:
    """The glyph for a tool, for the left gutter of a transcript row."""
    return spec_for(name).icon


def is_read_only(name: str, tool: Any = None) -> bool:
    """Whether a call is an *observation* rather than an action.

    A tool's own ``read_only`` attribute wins — the same precedence the
    permission engine uses — so a custom tool can declare itself.
    """
    declared = getattr(tool, "read_only", None)
    if isinstance(declared, bool):
        return declared
    # Registrations first, then the built-in table — same order as spec_for.
    # A tool in neither falls through to the permission heuristics rather than
    # to the humanized fallback, whose read_only default is a guess.
    known = _OVERRIDES.get(name) or VERBS.get(name)
    if known is not None:
        return known.read_only
    from shipit_agent.safety.permissions import PermissionEngine

    return PermissionEngine().is_read_only(name, tool)


# Verbs that read naturally with an object and dangle without one.
_TRAILING_PREPOSITIONS = frozenset({
    "for", "at", "to", "the", "of", "in", "on", "from", "with", "into",
})


def _bare(verb: str) -> str:
    """The verb with no object — ``Searched for`` → ``Searched``.

    A model can call a search tool without a pattern (or with an argument
    name we do not recognise), and "Searched for ›" with nothing after it
    reads as a truncation bug rather than a search.
    """
    words = verb.split()
    while len(words) > 1 and words[-1].lower() in _TRAILING_PREPOSITIONS:
        words.pop()
    return " ".join(words) or verb


@dataclass(frozen=True, slots=True)
class ToolSummary:
    """One call, narrated. ``target`` is ``None`` for an intransitive verb."""

    name: str
    past: str
    present: str
    target: str | None
    icon: str
    read_only: bool

    def past_label(self) -> str:
        """``Read app.py`` — what the transcript shows once the call lands."""
        return (
            f"{self.past} {self.target}" if self.target else _bare(self.past)
        )

    def present_label(self) -> str:
        """``Reading app.py`` — what it shows while the call is in flight."""
        return (
            f"{self.present} {self.target}" if self.target else _bare(self.present)
        )


def summarize(name: str, arguments: dict[str, Any] | None = None) -> ToolSummary:
    """Narrate a single tool call.

    Never raises and never returns an empty label: an unknown tool with
    unreadable arguments still yields something a human can read.
    """
    args = dict(arguments or {})
    spec = spec_for(name)
    override = _SUMMARY_OVERRIDES.get(name)
    if override is not None and name not in _OVERRIDES:
        # A registration wins over the built-in override, so a project can
        # still re-narrate the tool however it likes.
        past, present, target = override(args)
        return ToolSummary(
            name=name, past=past, present=present, target=target,
            icon=spec.icon, read_only=is_read_only(name),
        )
    target = _extract_target(name, args, spec)
    return ToolSummary(
        name=name,
        past=spec.past,
        present=spec.present,
        target=target,
        icon=spec.icon,
        read_only=is_read_only(name),
    )


def _count_phrase(spec: VerbSpec, count: int) -> str:
    if spec.noun:
        return pluralize(count, spec.noun, spec.plural)
    return pluralize(count, "time")


def describe_count(name: str, count: int) -> str:
    """Count-aware past label — ``Wrote 5 files``, ``Ran code 3 times``.

    A single call reads as the plain verb, so ``Made 1 edit`` never appears.
    """
    spec = spec_for(name)
    if count <= 1:
        return spec.past
    if spec.intransitive:
        return f"{spec.past} {pluralize(count, 'time')}"
    verb = spec.count_verb[0] if spec.count_verb else spec.past
    return f"{verb} {_count_phrase(spec, count)}"


def describe_count_present(name: str, count: int) -> str:
    """Count-aware present label — ``Writing 5 files``."""
    spec = spec_for(name)
    if count <= 1:
        return spec.present
    if spec.intransitive:
        return f"{spec.present} {pluralize(count, 'time')}"
    verb = spec.count_verb[1] if spec.count_verb else spec.present
    return f"{verb} {_count_phrase(spec, count)}"
