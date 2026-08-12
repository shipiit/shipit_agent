"""Permission engine — a fast, rule-based control plane for tool calls.

A rule-based permission layer: every proposed tool call is
checked against declarative **allow / deny / ask** rules and a **mode** before
it runs — no LLM required (unlike :mod:`shipit_agent.verifier`, which is an
*LLM* veto and complements this). The two can run together: the permission
engine is the cheap first gate; the verifier is the smart second opinion.

Modes:

- ``default``     — apply rules; unmatched tools fall back to ``default_decision``.
- ``acceptEdits`` — auto-allow file edit/write tools; everything else via rules.
- ``plan``        — read-only gate: only known read-only tools run; every
                    mutating/unknown tool is denied so the agent must produce a
                    plan instead of acting.
- ``bypass``      — allow everything (escape hatch; use with care).

A check returns a :class:`PermissionResult` with a decision and, optionally,
``updated_arguments`` to **rewrite** the tool call (e.g. redact a secret, scope
a path) before it executes.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal

PermissionMode = Literal["default", "acceptEdits", "plan", "bypass"]


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(slots=True)
class PermissionResult:
    """The outcome of a permission check.

    ``updated_arguments`` lets a rule/hook **rewrite** the call before it runs
    (an argument rewrite). ``None`` means "use the original args".
    """

    decision: PermissionDecision
    reason: str = ""
    updated_arguments: dict[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == PermissionDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == PermissionDecision.DENY

    @property
    def needs_approval(self) -> bool:
        return self.decision == PermissionDecision.ASK


# Default name heuristics. Overridable per-engine, and a tool may declare its
# own ``read_only: bool`` attribute which always wins over these.
_DEFAULT_READ_ONLY: tuple[str, ...] = (
    "read*", "*read*", "view*", "list*", "glob*", "grep*", "search*",
    "web_search", "open_url", "get_*", "fetch*", "*_get", "*_list",
    "*_search", "plan*", "decompose*", "synthesize*", "decision*",
    "verify*", "build_prompt", "tool_search", "ask_user", "human_review",
)
_DEFAULT_MUTATING: tuple[str, ...] = (
    "write*", "edit*", "*write*", "bash", "run_code", "code_execution",
    "*_create", "*_update", "*_delete", "*send*", "*_post", "sql",
    "build_artifact", "*_patch",
)
_EDIT_TOOLS: tuple[str, ...] = ("write*", "edit*", "*write*", "build_artifact")


def _matches_any(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


@dataclass
class PermissionEngine:
    """Rule-based gate for tool calls.

    ``allow`` / ``deny`` / ``ask`` are lists of tool-name globs (``fnmatch``).
    Precedence: ``deny`` > mode logic > ``allow`` > ``ask`` > ``callback`` >
    ``default_decision``.

    Because ``deny`` outranks ``allow``, ``deny=["*"]`` denies **everything**,
    including anything you allow-listed — it is not "deny the rest". To mean
    "these tools and nothing else", allow-list them and flip the default::

        PermissionEngine(
            allow=["read_file", "grep_files"],
            default_decision=PermissionDecision.DENY,
        )
    """

    mode: PermissionMode = "default"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    default_decision: PermissionDecision = PermissionDecision.ALLOW
    read_only_tools: tuple[str, ...] = _DEFAULT_READ_ONLY
    mutating_tools: tuple[str, ...] = _DEFAULT_MUTATING
    edit_tools: tuple[str, ...] = _EDIT_TOOLS
    # canUseTool-style callback: (name, args) -> PermissionResult | None.
    # Returning None defers to the default decision.
    callback: Callable[[str, dict[str, Any]], PermissionResult | None] | None = None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    def is_read_only(self, tool_name: str, tool: Any = None) -> bool:
        """Is this call an observation?

        Precedence: the tool's own ``read_only`` attribute, then a declared
        :class:`~shipit_agent.tools.contracts.ToolContract`, then the name
        globs below. The globs used to be the only answer; they are now the
        fallback for tools nobody has declared.
        """
        ro = getattr(tool, "read_only", None)
        if isinstance(ro, bool):
            return ro
        declared = self._declared_read_only(tool_name)
        if declared is not None:
            return declared
        if _matches_any(tool_name, self.mutating_tools):
            return False
        return _matches_any(tool_name, self.read_only_tools)

    @staticmethod
    def _declared_read_only(tool_name: str) -> bool | None:
        """``read_only`` from a declared contract, or ``None`` if undeclared.

        Reads the tables directly rather than calling ``contract_for``, which
        would recurse back here for anything undeclared.
        """
        from shipit_agent.tools.contracts import CONTRACTS, registered_contracts

        contract = registered_contracts().get(tool_name) or CONTRACTS.get(tool_name)
        return None if contract is None else contract.read_only

    def is_edit(self, tool_name: str) -> bool:
        return _matches_any(tool_name, self.edit_tools)

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    def check(
        self, tool_name: str, arguments: dict[str, Any], tool: Any = None
    ) -> PermissionResult:
        # 1. Hard deny rules always win.
        if _matches_any(tool_name, self.deny):
            return PermissionResult(
                PermissionDecision.DENY,
                reason=f"'{tool_name}' is on the deny list.",
            )

        # 2. Mode logic.
        if self.mode == "bypass":
            return PermissionResult(PermissionDecision.ALLOW, reason="bypass mode")

        if self.mode == "plan":
            # present_plan is the exit affordance: it produces a plan for
            # approval, so it is always allowed in plan mode even though it
            # is the thing plan mode is building toward.
            if (
                tool_name == "present_plan"
                or _matches_any(tool_name, self.allow)
                or self.is_read_only(tool_name, tool)
            ):
                return PermissionResult(
                    PermissionDecision.ALLOW, reason="read-only (plan mode)"
                )
            return PermissionResult(
                PermissionDecision.DENY,
                reason=(
                    "Plan mode is read-only — do not call mutating tools. "
                    "Research read-only, then call present_plan with your "
                    "step-by-step plan and stop for approval."
                ),
            )

        if self.mode == "acceptEdits" and self.is_edit(tool_name):
            return PermissionResult(
                PermissionDecision.ALLOW, reason="auto-approved edit (acceptEdits)"
            )

        # 3. Explicit allow / ask rules.
        if _matches_any(tool_name, self.allow):
            return PermissionResult(PermissionDecision.ALLOW, reason="allow rule")
        if _matches_any(tool_name, self.ask):
            asked = self._consult_callback(tool_name, arguments)
            if asked is not None:
                return asked
            return PermissionResult(
                PermissionDecision.ASK,
                reason=f"'{tool_name}' requires approval (ask rule).",
            )

        # 4. Callback (canUseTool) as a catch-all, then the default.
        asked = self._consult_callback(tool_name, arguments)
        if asked is not None:
            return asked
        return PermissionResult(self.default_decision, reason="default")

    def _consult_callback(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> PermissionResult | None:
        if self.callback is None:
            return None
        try:
            result = self.callback(tool_name, dict(arguments))
        except Exception:
            return None
        return result if isinstance(result, PermissionResult) else None


def authorize_tool(
    hooks: Any,
    permissions: "PermissionEngine | None",
    name: str,
    arguments: dict[str, Any],
    tool: Any = None,
) -> PermissionResult | None:
    """Fold blocking hooks + the permission engine into one decision.

    Precedence: DENY wins, then ASK, otherwise ALLOW (carrying the last
    argument rewrite). Returns ``None`` when neither has an opinion — the
    historical fully-permissive default. Shared by the sync and async runtimes.
    ``hooks`` is duck-typed (``run_before_tool(name, args)``) to avoid a circular
    import.
    """
    results: list[PermissionResult] = []
    if hooks is not None:
        hook_decision = hooks.run_before_tool(name, arguments)
        if hook_decision is not None:
            results.append(hook_decision)
    if permissions is not None:
        results.append(permissions.check(name, arguments, tool))
    if not results:
        return None
    for result in results:
        if result.denied:
            return result
    for result in results:
        if result.needs_approval:
            return result
    updated: dict[str, Any] | None = None
    for result in results:
        if result.updated_arguments is not None:
            updated = result.updated_arguments
    return PermissionResult(PermissionDecision.ALLOW, updated_arguments=updated)


def coerce_permissions(
    spec: PermissionEngine | PermissionMode | dict[str, Any] | None,
) -> PermissionEngine | None:
    """Normalize a user-supplied permissions spec into a ``PermissionEngine``.

    Accepts an engine, a bare mode string, a dict of kwargs, or ``None``.
    """
    if spec is None:
        return None
    if isinstance(spec, PermissionEngine):
        return spec
    if isinstance(spec, str):
        return PermissionEngine(mode=spec)  # type: ignore[arg-type]
    if isinstance(spec, dict):
        return PermissionEngine(**spec)
    raise TypeError(f"Unsupported permissions spec: {type(spec)!r}")
