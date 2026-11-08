"""Bindings — turn 50 tool schemas into a handful of `env` capabilities.

Cloudflare OS gives its model **14 tools**. There is no `github` tool, no
`slack` tool, no `sql` tool. Every external resource is a *binding* in `env`,
reached from one `executeCode` call, and the agent learns a binding's API on
demand with `describeBinding` rather than carrying every signature in its
prompt forever.

The size difference is not cosmetic. shipit ships 50 tool schemas on **every**
model call — thousands of tokens, paid on every turn of every run, whether or
not the agent touches Stripe. The reference design pays a few hundred, and
adding an integration costs nothing extra.

This module is the binding half. A binding wraps one existing tool and exposes
its `action` enum as methods::

    env.GITHUB.create_issue(owner="acme", repo="web", title="Fix login")
    # → GitHubTool.run(action="create_issue", owner=..., repo=..., title=...)

Two properties hold, and both are load-bearing:

- **A binding call is never more privileged than the tool call it wraps.**
  Every invocation goes back through the same permission engine, the same
  contracts, and the same approval queue. Code mode changes the *interface*,
  not the *authority*.
- **Nothing is guessed.** Methods, parameters, and read-only-ness are derived
  from the tool's own declared schema and :mod:`shipit_agent.tools.contracts`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from shipit_agent.tools.contracts import contract_for

from .binding_types import Binding as Binding
from .binding_types import BindingMethod as BindingMethod

__all__ = [
    "BindingMethod",
    "Binding",
    "build_binding",
    "build_bindings",
    "binding_name_for",
]

# The single method a tool gets when its schema declares no `action` enum.
DEFAULT_METHOD = "call"

# Parameter names that select the operation rather than describe it.
_ACTION_KEYS = ("action", "operation", "op", "command_type")


def binding_name_for(tool_name: str) -> str:
    """``google_sheets`` → ``SHEETS``; ``linkedin_search`` → ``LINKEDIN``.

    Upper snake case, because a binding is a constant in the agent's
    environment rather than a function it calls. Redundant ``_tool`` /
    ``_search`` suffixes are dropped so the name reads as the *resource*.
    """
    cleaned = re.split(r"__|\.", tool_name)[-1] or tool_name
    parts = [p for p in re.split(r"[_\-\s]+", cleaned) if p]
    if len(parts) > 1 and parts[-1].lower() in ("tool", "search", "api"):
        parts = parts[:-1]
    if parts and parts[0].lower() == "google" and len(parts) > 1:
        parts = parts[1:]  # google_sheets → SHEETS
    return "_".join(parts).upper() or tool_name.upper()


# ── construction ─────────────────────────────────────────────────────────


def _schema_of(tool: Any) -> dict[str, Any]:
    try:
        schema = tool.schema() or {}
    except Exception:
        return {}
    return schema.get("function", schema) if isinstance(schema, dict) else {}


def _action_key(properties: dict[str, Any]) -> str | None:
    """The parameter that selects the operation, if the schema has one."""
    for key in _ACTION_KEYS:
        spec = properties.get(key)
        if isinstance(spec, dict) and isinstance(spec.get("enum"), list):
            return key
    return None


def build_binding(
    tool: Any,
    *,
    invoke: Callable[[str, dict[str, Any]], Any] | None = None,
    catalog: Any = None,
    name: str | None = None,
) -> Binding:
    """Wrap one tool as an ``env`` binding.

    A tool whose schema declares an ``action`` enum becomes a binding with one
    method per action. Anything else gets a single ``call`` method carrying the
    tool's parameters — still useful, since it is reachable from code and
    composes with everything else in one call.
    """
    tool_name = str(getattr(tool, "name", "") or "tool")
    schema = _schema_of(tool)
    parameters = schema.get("parameters") or {}
    properties: dict[str, Any] = dict(parameters.get("properties") or {})
    required = tuple(parameters.get("required") or ())
    description = str(schema.get("description") or getattr(tool, "description", "") or "")

    action_key = _action_key(properties)
    methods: dict[str, BindingMethod] = {}

    if action_key:
        action_spec = properties.pop(action_key)
        rest_required = tuple(r for r in required if r != action_key)
        # A tool may narrow each action to the parameters it actually uses by
        # declaring `action_parameters = {action: (names...)}`. Without it we
        # fall back to the shared bag, which is imprecise but never wrong.
        per_action = getattr(tool, "action_parameters", None)
        per_action = per_action if isinstance(per_action, dict) else {}
        for action in action_spec.get("enum") or []:
            action = str(action)
            names = per_action.get(action)
            if names:
                subset = {k: v for k, v in properties.items() if k in set(names)}
                methods[action] = BindingMethod(
                    name=action,
                    description="",
                    parameters=subset,
                    required=tuple(r for r in rest_required if r in subset),
                )
            else:
                methods[action] = BindingMethod(
                    name=action,
                    description="",
                    parameters=properties,
                    required=rest_required,
                )
    else:
        methods[DEFAULT_METHOD] = BindingMethod(
            name=DEFAULT_METHOD,
            description=description,
            parameters=properties,
            required=required,
        )

    return Binding(
        name=name or binding_name_for(tool_name),
        tool_name=tool_name,
        title=tool_name.replace("_", " "),
        description=description,
        methods=methods,
        contract=contract_for(tool_name, tool),
        tool=tool,
        invoke=invoke,
        catalog=catalog,
    )


def build_bindings(
    tools: Iterable[Any],
    *,
    invoke_for: Callable[[Any], Callable[[str, dict[str, Any]], Any]] | None = None,
    catalogs: dict[str, Any] | None = None,
) -> dict[str, Binding]:
    """Build the whole ``env`` namespace, keyed by binding name.

    Name collisions are resolved by suffixing rather than silently dropping a
    resource — losing a binding would make the agent's environment differ from
    what its prompt says it is.
    """
    bindings: dict[str, Binding] = {}
    for tool in tools:
        tool_name = str(getattr(tool, "name", "") or "")
        if not tool_name:
            continue
        binding = build_binding(
            tool,
            invoke=invoke_for(tool) if invoke_for else None,
            catalog=(catalogs or {}).get(tool_name),
        )
        base = binding.name
        suffix = 2
        while binding.name in bindings:
            binding.name = f"{base}_{suffix}"
            suffix += 1
        bindings[binding.name] = binding
    return bindings
