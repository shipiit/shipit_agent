"""The deferral gate — one implementation, both runtimes.

``runtime.py`` and ``async_runtime.py`` are parallel implementations of the
same loop, and every past divergence between them has been a bug (the
``tool_denied`` payload was missing in both, and got fixed in only one for a
while). Gate semantics are exactly the kind of thing that must not drift, so
the decision lives here and both loops call it.
"""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.models import Message, ToolResult

__all__ = ["DeferralOutcome", "defer_tool_call"]


class DeferralOutcome:
    """What the gate decided.

    ``handled`` is False when the call must not be deferred — the caller then
    applies its normal blocking gate, unchanged.
    """

    __slots__ = ("handled", "result", "message", "action", "applied")

    def __init__(
        self,
        *,
        handled: bool,
        result: ToolResult | None = None,
        message: Message | None = None,
        action: Any = None,
        applied: bool = False,
    ) -> None:
        self.handled = handled
        self.result = result
        self.message = message
        self.action = action
        self.applied = applied


def defer_tool_call(
    *,
    approvals: Any,
    tool: Any,
    tool_call: Any,
    call_id: str,
    apply_fn: Callable[[], ToolResult],
) -> DeferralOutcome:
    """Queue a side-effecting call for later approval, if it may be deferred.

    Returns ``handled=False`` when the call must go through the normal gate:

    - there is no queue, or
    - the tool is an **observation** — there is no effect to defer, and the
      agent needs the data now or not at all, so "later" is meaningless, or
    - the contract sets ``await_decision`` — the agent will reason over the
      result, and letting it continue against state the action never touched
      makes it re-try, second-guess, and undo its own work.

    Otherwise the call is queued, an auto-approval drain runs (so a covered
    action never lingers as "pending"), and the agent is handed either the
    real result — if a rule applied it — or an honest deferral notice.
    """
    if approvals is None:
        return DeferralOutcome(handled=False)

    from shipit_agent.tools.contracts import contract_for

    contract = contract_for(tool_call.name, tool)
    if contract.read_only or contract.await_decision:
        return DeferralOutcome(handled=False)

    action = approvals.submit(
        tool=tool_call.name,
        arguments=dict(tool_call.arguments),
        apply_fn=apply_fn,
        contract=contract,
    )
    approvals.drain(by="auto-approval")

    if not action.is_pending and isinstance(action.result, ToolResult):
        result = action.result
        return DeferralOutcome(
            handled=True,
            applied=True,
            action=action,
            result=result,
            message=Message(
                role="tool",
                name=tool_call.name,
                content=result.output,
                metadata={
                    **dict(result.metadata),
                    "tool_call_id": call_id,
                    "auto_approved": True,
                    "action_id": action.id,
                },
            ),
        )

    return DeferralOutcome(
        handled=True,
        applied=False,
        action=action,
        result=None,
        message=Message(
            role="tool",
            name=tool_call.name,
            content=action.deferral_notice(),
            metadata={
                "tool_call_id": call_id,
                "queued": True,
                "action_id": action.id,
            },
        ),
    )
