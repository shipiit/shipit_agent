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
CORE_TOOLS: frozenset[str] = frozenset({
    # the working copy
    "read_file", "write_file", "edit_file", "glob_files", "grep_files",
    # the shell and the sandbox
    "bash", "execute_code",
    # discovery
    "describe_binding", "tool_search", "call_tool",
    # the open web is not a connected resource
    "web_search", "open_url",
    # talking to the human
    "ask_user", "give_up",
    # the agent's own scaffolding
    "todo",
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
