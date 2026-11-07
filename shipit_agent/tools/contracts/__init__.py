"""Tool contracts — what a tool *is*, declared rather than guessed.

Today shipit infers a tool's nature from its **name**: ``permissions.py``
matches ``bash`` and ``*_delete`` against glob lists to decide whether a call
mutates anything. That works until a tool is called ``figma`` or
``linear__create_issue``, at which point the guess is silent and wrong.

Cloudflare OS makes every operation declare itself instead — an
``ObservationDescription`` (read-only, runs immediately) or an
``ActionDescription`` carrying ``implementsRevert``, ``awaitDecision``,
``autoApprovable``, and a stable ``actionKind {tag, label}``. Every downstream
decision — approve, auto-approve, defer, revert, how to render it — reads those
fields. The polish is downstream of the declaration.

This module is that layer for shipit. :data:`CONTRACTS` gives every built-in a
:class:`ToolContract`; :func:`register_contract` lets a project declare its own
tools or override ours; :func:`contract_for` resolves in a fixed order:

1. the tool object's own attributes (``read_only``, ``action_kind``, …)
2. a registration
3. the built-in table
4. name heuristics — the old behaviour, now only a last resort

The package: ``types`` (the contract and action kinds), ``table`` (the
built-ins), and here registration and resolution.

Nothing here changes what a tool *does*. It states what a tool *is*, so the
permission engine, the approval queue, and the Narrator can stop guessing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .table import CONTRACTS
# Every action kind stays importable from here, as it was from the module.
from .types import (
    AGENT_STATE as AGENT_STATE,
    ARTIFACT_WRITE as ARTIFACT_WRITE,
    BROWSER_ACT as BROWSER_ACT,
    CALENDAR_WRITE as CALENDAR_WRITE,
    CODE_EXEC as CODE_EXEC,
    COMMS_SEND as COMMS_SEND,
    CRM_WRITE as CRM_WRITE,
    DB_WRITE as DB_WRITE,
    DOC_WRITE as DOC_WRITE,
    FS_DELETE as FS_DELETE,
    FS_WRITE as FS_WRITE,
    HUMAN_ASK as HUMAN_ASK,
    ISSUE_WRITE as ISSUE_WRITE,
    MEMORY_WRITE as MEMORY_WRITE,
    NET_WRITE as NET_WRITE,
    PAYMENT_WRITE as PAYMENT_WRITE,
    SHELL_EXEC as SHELL_EXEC,
    VCS_WRITE as VCS_WRITE,
    OBSERVE,
    ActionKind,
    ToolContract,
)

__all__ = [
    "ActionKind",
    "ToolContract",
    "CONTRACTS",
    "OBSERVE",
    "contract_for",
    "register_contract",
    "register_contracts",
    "unregister_contract",
    "registered_contracts",
    "action_kinds",
]


# ── Registration ─────────────────────────────────────────────────────────

_OVERRIDES: dict[str, ToolContract] = {}


def register_contract(name: str, contract: ToolContract) -> None:
    """Declare what a tool is, or override a built-in declaration::

        from shipit_agent.tools.contracts import (
            ActionKind, ToolContract, register_contract,
        )

        register_contract(
            "deploy_service",
            ToolContract(
                action_kind=ActionKind("deploy.write", "Deploy a service"),
                await_decision=True,
                destructive=True,
            ),
        )
    """
    if not isinstance(contract, ToolContract):
        raise TypeError(f"expected ToolContract, got {type(contract).__name__}")
    _OVERRIDES[name] = contract


def register_contracts(contracts: dict[str, ToolContract]) -> None:
    """Declare several at once — see :func:`register_contract`."""
    for name, contract in (contracts or {}).items():
        register_contract(name, contract)


def unregister_contract(name: str) -> None:
    """Drop a registration, restoring the built-in (or the heuristics)."""
    _OVERRIDES.pop(name, None)


def registered_contracts() -> dict[str, ToolContract]:
    """The currently registered overrides (a copy)."""
    return dict(_OVERRIDES)


def action_kinds() -> list[ActionKind]:
    """Every distinct action kind currently declared, sorted by tag.

    This is what an "always approve…" settings screen lists — the *potential*
    set, available before any action has been submitted.
    """
    seen: dict[str, ActionKind] = {}
    for contract in (*CONTRACTS.values(), *_OVERRIDES.values()):
        if contract.action_kind is not None:
            seen.setdefault(contract.action_kind.tag, contract.action_kind)
    return sorted(seen.values(), key=lambda kind: kind.tag)


# ── Resolution ───────────────────────────────────────────────────────────


def _from_tool_object(tool: Any) -> ToolContract | None:
    """Read a contract off the tool itself, if it declares one.

    Supports both a whole ``contract`` attribute and the loose attributes
    tools already use (``read_only`` on ``SqlTool`` today), so a tool that
    declares only ``read_only = True`` still gets an accurate contract.
    """
    if tool is None:
        return None
    declared = getattr(tool, "contract", None)
    if isinstance(declared, ToolContract):
        return declared
    read_only = getattr(tool, "read_only", None)
    kind = getattr(tool, "action_kind", None)
    if not isinstance(read_only, bool) and not isinstance(kind, ActionKind):
        return None
    if read_only is True:
        return OBSERVE
    return ToolContract(
        read_only=False,
        action_kind=kind if isinstance(kind, ActionKind) else None,
        implements_revert=bool(getattr(tool, "implements_revert", False)),
        await_decision=bool(getattr(tool, "await_decision", True)),
        destructive=bool(getattr(tool, "destructive", False)),
    )


def _from_heuristics(name: str, tool: Any) -> ToolContract:
    """Last resort — the historical name-glob behaviour, made explicit.

    An MCP server we've never seen still gets a usable contract: read-only if
    it looks read-only, otherwise an untagged action, which is the safe
    reading (untagged means it can never be auto-approved).
    """
    from shipit_agent.safety.permissions import PermissionEngine

    if PermissionEngine().is_read_only(name, tool):
        return OBSERVE
    # Unknown and mutating: gate it, every time, and make the agent wait —
    # we have no idea whether its result is load-bearing.
    return ToolContract(await_decision=True)


def contract_for(name: str, tool: Any = None) -> ToolContract:
    """The contract for a tool: declaration → registration → table → guess.

    Never raises and always returns a contract, so every caller can rely on
    the fields being there.
    """
    from_tool = _from_tool_object(tool)
    if from_tool is not None:
        return from_tool
    override = _OVERRIDES.get(name)
    if override is not None:
        return override
    builtin = CONTRACTS.get(name)
    if builtin is not None:
        return builtin
    return _from_heuristics(name, tool)


def with_overrides(base: ToolContract, **changes: Any) -> ToolContract:
    """A copy of *base* with fields replaced — for per-call refinement."""
    return replace(base, **changes)
