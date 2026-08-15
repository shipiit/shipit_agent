"""Human-in-the-loop tool confirmation — a first-class, ADK-grade decorator.

shipit already gates tools through a :class:`~shipit_agent.permissions.PermissionPolicy`
(allow / ask / deny) and an approval queue. This module adds the ergonomic that
makes HITL powerful: a tool declares *for itself* when it needs a human "yes",
in one decorator — and that requirement is a **floor** no bypass/allow mode can
silently skip.

It goes past a plain yes/no, matching a Google-ADK-style tool confirmation:

- **Always confirm** ::

      @requires_confirmation("Deletes files permanently — cannot be undone.")
      class DeleteTool: ...

- **Confirm only when it matters** — a predicate over the call's arguments, so a
  cheap call runs free and only the dangerous one pauses ::

      @requires_confirmation(
          "Large wire transfer needs sign-off.",
          impact="irreversible",
          when=lambda args: args.get("amount", 0) >= 10_000,
      )
      def wire_transfer(amount: float, to: str) -> str: ...

- **Impact levels** (`default` · `destructive` · `irreversible`) so a UI can
  colour the approval card by severity.

- **Approve-with-edit** — because the answer flows through the existing approval
  machinery, a human can approve *and modify the arguments* (the policy returns
  ``updated_arguments``); nothing here has to special-case that.

The actual yes/no still travels through the console prompt / approval queue / UI
you already use — this module only decides *whether* to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, overload

#: Where the parsed requirement is stashed on a tool class/function.
CONFIRM_SPEC_ATTR = "_tool_confirmation"
#: Back-compat boolean flag (older code / the permission gate both read it).
CONFIRM_ATTR = "requires_confirmation"

Predicate = Callable[[dict[str, Any]], bool]
IMPACTS = ("default", "destructive", "irreversible")


@dataclass(slots=True)
class ToolConfirmation:
    """A tool's declared confirmation requirement.

    ``when`` makes it conditional: return ``True`` to demand approval for this
    particular call, ``False`` to let it run. Omit it to always confirm.
    """

    message: str = ""
    impact: str = "default"
    when: Predicate | None = None

    def applies(self, arguments: dict[str, Any] | None) -> bool:
        """Does this call need confirmation? Fail *safe* — ask on a bad predicate."""
        if self.when is None:
            return True
        try:
            return bool(self.when(arguments or {}))
        except Exception:  # noqa: BLE001 — a broken predicate must not skip the gate
            return True

    def reason(self, tool_name: str) -> str:
        return self.message or f"'{tool_name}' requires confirmation before it runs."


def _mark(target: Any, spec: ToolConfirmation) -> Any:
    try:
        setattr(target, CONFIRM_SPEC_ATTR, spec)
        setattr(target, CONFIRM_ATTR, True)  # keep the simple flag readable too
    except (AttributeError, TypeError):
        raise TypeError(
            "requires_confirmation can't mark this object — decorate the tool "
            "class or function, not a slotted/builtin instance."
        ) from None
    return target


@overload
def requires_confirmation(target: Callable[..., Any] | type) -> Any: ...
@overload
def requires_confirmation(
    target: str = ..., *, impact: str = ..., when: Predicate | None = ...
) -> Callable[[Any], Any]: ...
@overload
def requires_confirmation(
    *, message: str, impact: str = ..., when: Predicate | None = ...
) -> Callable[[Any], Any]: ...


def requires_confirmation(
    target: Any = None,
    *,
    message: str | None = None,
    impact: str = "default",
    when: Predicate | None = None,
) -> Any:
    """Mark a tool so it asks a human before running.

    Call styles (all equivalent for the message):

    - ``@requires_confirmation`` — bare, always confirm.
    - ``@requires_confirmation("why it's dangerous")`` — positional message.
    - ``@requires_confirmation(message="…", impact="irreversible", when=fn)``.

    ``impact`` ∈ ``{"default","destructive","irreversible"}`` (invalid values
    fall back to ``"default"``). ``when(arguments) -> bool`` makes it conditional.
    """
    if impact not in IMPACTS:
        impact = "default"

    # @requires_confirmation("message")  → target is the message
    if isinstance(target, str):
        message = target
        target = None

    spec = ToolConfirmation(message=message or "", impact=impact, when=when)

    if target is None:
        return lambda obj: _mark(obj, spec)
    # @requires_confirmation (bare) → target is the class/function
    return _mark(target, spec)


def confirmation_spec(tool: Any) -> ToolConfirmation | None:
    """The :class:`ToolConfirmation` a tool declared, or ``None``.

    Honours both the rich spec and a bare ``requires_confirmation = True`` flag
    set by hand, so either style works at the gate.
    """
    spec = getattr(tool, CONFIRM_SPEC_ATTR, None)
    if isinstance(spec, ToolConfirmation):
        return spec
    if getattr(tool, CONFIRM_ATTR, False):
        return ToolConfirmation()
    return None


def needs_confirmation(tool: Any, arguments: dict[str, Any] | None = None) -> bool:
    """True if this tool needs confirmation *for this call* (evaluates ``when``)."""
    spec = confirmation_spec(tool)
    return spec is not None and spec.applies(arguments)
