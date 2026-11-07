"""What a contract says about a tool, and the action kinds it can name."""

from __future__ import annotations

from dataclasses import dataclass


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
