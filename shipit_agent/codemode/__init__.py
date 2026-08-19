"""Code mode — a small `env` of capabilities instead of 50 tool schemas.

Stage 4 of the modern-agent upgrade (``docs/design/modern-agent-upgrade.md``).
See :mod:`shipit_agent.codemode.bindings` for the rationale.
"""

from .bindings import (
    Binding,
    BindingMethod,
    binding_name_for,
    build_binding,
    build_bindings,
)
from .bridge import BridgeCall, BridgeLimits, BridgeServer
from .catalog import (
    CatalogEntry,
    ResourceCatalog,
    load_catalog,
    normalize_catalog,
)

__all__ = [
    "Binding",
    "BridgeCall",
    "BridgeLimits",
    "BridgeServer",
    "BindingMethod",
    "CatalogEntry",
    "ResourceCatalog",
    "binding_name_for",
    "build_binding",
    "build_bindings",
    "load_catalog",
    "normalize_catalog",
]


# Tools that stay as tools in code mode. Everything else becomes an `env`
# binding, reachable from execute_code.
#
# The split is by what the agent does *directly* versus what it reaches
# *through* a resource: editing the repo it is working in, searching it, and
# its own reasoning scaffolding are direct. GitHub, Slack, Stripe and the rest
# are resources, and cost nothing in the prompt until asked about.
#: The tools whose schemas stay resident on every call under
#: ``deferred_tools=True``. Everything else is name-only until ``tool_search``
#: loads it, so this set is the token FLOOR of a deferred agent — 25 tools at
#: ~307 tokens of schema each was the entire ~7,400-token first turn before the
#: user said anything. It now holds one tool per capability, no synonyms:
#: twelve of the old 25 were the same capability under different names, and a
#: model choosing between ``bash`` / ``run_code`` / ``execute_code`` guesses
#: right about a third of the time. Nothing is lost — every dropped name is
#: still reachable through ``tool_search``.
CORE_TOOLS: frozenset[str] = frozenset({
    # the working copy
    "read_file", "write_file", "edit_file", "glob_files", "grep_files",
    # the shell — one way to run code; the language is an argument
    "bash",
    # code mode's sandbox + resource introspection. This set is shared with
    # code mode (runtime.py filters non-core tools into `env`), which cannot
    # function without these two — so they stay resident even though a plain
    # deferred agent rarely needs them.
    "execute_code", "describe_binding",
    # discovery — without this the deferred tail is unreachable
    "tool_search",
    # the open web — fetching a result is a mode of search, not a capability
    "web_search",
    # talking to the human — sync vs async is a runtime concern, not model-visible
    "ask_user",
    # the agent's own scaffolding — one structure tool, not four
    "todo", "memory",
})


def binding_index(bindings: dict) -> str:
    """The system-prompt section listing what is in `env`.

    One line per resource — this is the whole cost of an integration in the
    prompt, versus a full JSON schema on every call.
    """
    if not bindings:
        return ""
    lines = [
        "You have these resources bound in `env`, reachable from the "
        "`execute_code` tool:",
        "",
    ]
    lines += [b.summary_line() for _, b in sorted(bindings.items())]
    lines += [
        "",
        "Call `describe_binding` with a resource's name to learn its methods "
        "before using it for the first time. Prefer one `execute_code` call "
        "that composes several resources over many separate tool calls.",
    ]
    return "\n".join(lines)
