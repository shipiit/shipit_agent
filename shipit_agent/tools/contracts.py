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

Nothing here changes what a tool *does*. It states what a tool *is*, so the
permission engine, the approval queue, and the Narrator can stop guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

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


@dataclass(frozen=True, slots=True)
class ActionKind:
    """A stable machine tag paired with the label a human reads.

    ``tag`` is what policy keys on — auto-approval rules group by it, so it is
    an enum in all but syntax and must stay stable across releases. Several
    tools may share a tag to be governed as one group (every connector that
    posts a message is ``comms.send``). ``label`` is display-only.
    """

    tag: str
    label: str


@dataclass(frozen=True, slots=True)
class ToolContract:
    """What a tool is, so nothing downstream has to infer it.

    ``read_only`` — an *observation*. Runs without approval, renders as a quiet
    collapsed row, never enters the approval queue.

    ``action_kind`` — required for an action to be auto-approvable at all;
    ``None`` means every call is a manual gate, permanently.

    ``implements_revert`` — can the effect be undone? Only true when a
    reverter is registered in :mod:`shipit_agent.approvals.revert`; a test
    enforces that, because an undo affordance that does nothing is worse than
    none. Filesystem writes qualify; connector writes need a per-vendor
    inverse operation and currently declare false.

    ``await_decision`` — the agent must **stop** and wait for the decision
    rather than continuing with the action queued. Set it when the call returns
    data the agent will reason over: a queued `bash` that the agent believes
    succeeded leads it to re-try, second-guess, or undo its own work. Leave it
    off for fire-and-forget effects (post a message, file a ticket) where
    "queued" is all the agent needs to know.

    ``auto_approvable`` — the author's standing verdict that calls of this kind
    are safe to apply without review *if* the user has opted in for the tag.
    Both signals are required; neither alone is sufficient.

    ``destructive`` — irreversible loss is possible. Never auto-approvable.
    """

    read_only: bool = False
    action_kind: ActionKind | None = None
    implements_revert: bool = False
    await_decision: bool = False
    auto_approvable: bool = False
    destructive: bool = False

    def __post_init__(self) -> None:
        # Two invariants worth failing loudly on, because a wrong value here
        # silently widens what runs without a human.
        if self.auto_approvable and self.action_kind is None:
            raise ValueError(
                "auto_approvable requires an action_kind — auto-approval rules "
                "key on the tag, so an untagged action can never match one."
            )
        if self.auto_approvable and self.destructive:
            raise ValueError("a destructive action must not be auto_approvable")

    @property
    def is_action(self) -> bool:
        return not self.read_only

    @property
    def tag(self) -> str | None:
        return self.action_kind.tag if self.action_kind else None


# ── The action-kind taxonomy ─────────────────────────────────────────────
# Coarse on purpose: a user granting "always approve" is answering a question
# about a *class* of effect, not about one tool. Tags are grouped by what the
# effect is on the world, not by which vendor provides it.

FS_WRITE = ActionKind("fs.write", "Write or edit a file")
FS_DELETE = ActionKind("fs.delete", "Delete a file")
SHELL_EXEC = ActionKind("shell.exec", "Run a shell command")
CODE_EXEC = ActionKind("code.exec", "Execute code")
NET_WRITE = ActionKind("net.write", "Send a request that changes remote state")
DB_WRITE = ActionKind("db.write", "Modify a database")
VCS_WRITE = ActionKind("vcs.write", "Change version control state")
COMMS_SEND = ActionKind("comms.send", "Send a message on your behalf")
ISSUE_WRITE = ActionKind("issue.write", "Create or update an issue or ticket")
DOC_WRITE = ActionKind("doc.write", "Create or update a document")
CRM_WRITE = ActionKind("crm.write", "Change customer or CRM records")
PAYMENT_WRITE = ActionKind("payment.write", "Move money or change billing")
CALENDAR_WRITE = ActionKind("calendar.write", "Change your calendar")
MEMORY_WRITE = ActionKind("memory.write", "Write to the agent's memory")
BROWSER_ACT = ActionKind("browser.act", "Interact with a web page")
ARTIFACT_WRITE = ActionKind("artifact.write", "Produce a deliverable")
HUMAN_ASK = ActionKind("human.ask", "Ask you a question")
AGENT_STATE = ActionKind("agent.state", "Update the agent's own working state")

# The observation contract, used by every read-only tool.
OBSERVE = ToolContract(read_only=True)


def _act(
    kind: ActionKind,
    *,
    revert: bool = False,
    await_decision: bool = False,
    auto: bool = False,
    destructive: bool = False,
) -> ToolContract:
    return ToolContract(
        action_kind=kind,
        implements_revert=revert,
        await_decision=await_decision,
        auto_approvable=auto,
        destructive=destructive,
    )


# ── Built-in contracts ───────────────────────────────────────────────────
# `await_decision` reasoning, applied consistently: a call whose *return value*
# the agent will reason over cannot be deferred without lying to it. A call
# whose effect is elsewhere (a message sent, a ticket filed) can.

CONTRACTS: dict[str, ToolContract] = {
    # ── files ────────────────────────────────────────────────────────────
    "read_file": OBSERVE,
    "glob_files": OBSERVE,
    "grep_files": OBSERVE,
    "workspace_files": OBSERVE,
    # Edits are reversible in a repo and the agent reads files back, so they
    # gate — but they are the archetypal "always approve this" case.
    "write_file": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "edit_file": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "notebook_edit": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "download_file": _act(FS_WRITE, revert=True, await_decision=True),
    # ── execution ────────────────────────────────────────────────────────
    # Never auto-approvable: the argument is arbitrary code, so the tag says
    # nothing about what this particular call does.
    "bash": _act(SHELL_EXEC, await_decision=True, destructive=True),
    "run_code": _act(CODE_EXEC, await_decision=True, destructive=True),
    # Same reasoning as run_code: the argument is arbitrary code, so the tag
    # says nothing about what this particular call does. Each env call inside
    # it is separately gated by its own binding's contract.
    "execute_code": _act(CODE_EXEC, await_decision=True, destructive=True),
    "git_ops": _act(VCS_WRITE, await_decision=True),
    # ── web ──────────────────────────────────────────────────────────────
    "web_search": OBSERVE,
    "open_url": OBSERVE,
    "deep_research": OBSERVE,
    "linkedin_search": OBSERVE,
    "gmail_search": OBSERVE,
    "playwright_browse": _act(BROWSER_ACT, await_decision=True),
    "custom_api": _act(NET_WRITE, await_decision=True),
    # ── data ─────────────────────────────────────────────────────────────
    # SQL is one tool for reads and writes; the contract takes the stricter
    # reading, and the tool's own `read_only` (it has one) refines per call.
    "sql": _act(DB_WRITE, await_decision=True, destructive=True),
    "google_sheets": _act(DB_WRITE, await_decision=True),
    # ── documents & deliverables ─────────────────────────────────────────
    "build_document": _act(ARTIFACT_WRITE, revert=True, auto=True),
    "build_artifact": _act(ARTIFACT_WRITE, revert=True, auto=True),
    "render_dashboard": _act(ARTIFACT_WRITE, revert=True, auto=True),
    "pdf": OBSERVE,
    "vision": OBSERVE,
    # ── connectors ───────────────────────────────────────────────────────
    # Sending is the one effect people most want a gate on, and the one that
    # least needs the agent to wait: "queued" is the whole result. Marked
    # auto-approvable because "always approve sending on my behalf" is a
    # coherent informed choice — and it still takes the user enabling the rule
    # before anything applies. Not revertible: you cannot unsend.
    "slack": _act(COMMS_SEND, auto=True),
    "zendesk": _act(COMMS_SEND, auto=True),
    "github": _act(VCS_WRITE, await_decision=True),
    "gitlab": _act(VCS_WRITE, await_decision=True),
    "jira": _act(ISSUE_WRITE, auto=True),
    "linear": _act(ISSUE_WRITE, auto=True),
    "notion": _act(DOC_WRITE, auto=True),
    "confluence": _act(DOC_WRITE, auto=True),
    "figma": _act(DOC_WRITE),
    "google_drive": _act(DOC_WRITE, await_decision=True),
    "google_calendar": _act(CALENDAR_WRITE),
    "salesforce": _act(CRM_WRITE, await_decision=True),
    "stripe": _act(PAYMENT_WRITE, await_decision=True, destructive=True),
    # ── humans ───────────────────────────────────────────────────────────
    # Asking is not an action to approve — it *is* the approval channel.
    "ask_user": OBSERVE,
    "ask_user_async": OBSERVE,
    "human_review": OBSERVE,
    # Saying "I am blocked" changes nothing; gating it would only silence it.
    "give_up": OBSERVE,
    # ── the agent's own reasoning ────────────────────────────────────────
    # These change nothing outside the run. Gating them would be noise.
    "plan_task": OBSERVE,
    "decompose_problem": OBSERVE,
    "synthesize_evidence": OBSERVE,
    "decision_matrix": OBSERVE,
    "verify_output": OBSERVE,
    "build_prompt": OBSERVE,
    "tool_search": OBSERVE,
    "describe_binding": OBSERVE,
    # Listing and requesting connections changes nothing itself.
    "connections": OBSERVE,
    "todo": _act(AGENT_STATE, auto=True),
    "memory": _act(MEMORY_WRITE, auto=True),
}


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
    from shipit_agent.permissions import PermissionEngine

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
