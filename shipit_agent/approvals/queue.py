"""The approval queue — approve later, in bulk, without stopping the agent.

The problem this solves, in Cloudflare OS's words:

    Traditionally, human-in-the-loop setups require the human to approve
    actions *synchronously*. […] you give your agent a task, then walk away
    and get a coffee, only to come back and find the agent got stuck on an
    approval on the first step. As a result, people often give in and set
    their agents to "auto-approve", or `--dangerously-skip-permissions`,
    which is, obviously, unsafe.

So: a side-effecting call the policy marks *ask* is **queued** rather than
blocked on. The agent is told the truth — "queued, not run, keep going, don't
retry" — and carries on. You decide later, one by one or all at once::

    queue = ApprovalQueue()
    agent = Agent.with_builtins(llm=llm, approvals=queue,
                                permissions=PermissionEngine(ask=["slack", "jira"]))
    agent.run("File tickets for every TODO and tell the team.")

    for action in queue.pending():
        print(action.title)          # "Used Slack #eng"
    queue.approve_all(by="rahul")    # or approve(id) / deny(id)

Two escape valves keep this honest:

- A tool whose **result the agent reasons over** (``bash``, ``sql``,
  ``run_code``) declares ``await_decision`` in its contract and is *not*
  queued — it still blocks, because letting the agent continue against state
  the action never touched makes it re-try, second-guess, and undo its own
  work. See :mod:`shipit_agent.tools.contracts`.
- Nothing is ever auto-applied past a manual gate. See :class:`AutoApprovalDrainer`.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable

from shipit_agent.tools.contracts import ActionKind, ToolContract, contract_for

from .models import ActionState, ApplyFn, PendingAction

__all__ = ["ApprovalQueue", "AutoApprovalDrainer", "AutoApproveRule"]


class AutoApproveRule:
    """A user's standing "always approve this kind" decision.

    ``enabled_by`` matters: an auto-approval runs under the authority of the
    person who enabled the rule, and the audit log says so.
    """

    __slots__ = ("tag", "label", "enabled_by", "enabled_at")

    def __init__(self, tag: str, label: str, enabled_by: str) -> None:
        self.tag = tag
        self.label = label
        self.enabled_by = enabled_by
        self.enabled_at = time.time()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AutoApproveRule({self.tag!r}, by={self.enabled_by!r})"


class AutoApprovalDrainer:
    """Applies eligible pending actions, in order, never skipping a gate.

    A direct port of Cloudflare OS's ``AutoApprovalDrainer``, including the
    three properties that make it safe:

    1. **In id order, stopping at the first ineligible action.** A pending
       action awaiting a manual decision is never jumped over — otherwise
       "approve later" could silently reorder your effects.
    2. **Both signals required** — the contract's ``auto_approvable`` verdict
       *and* an enabled rule for its tag.
    3. **Single-flight with a rerun flag**, so two concurrent drains can't
       double-apply, and work submitted mid-drain isn't lost.
    """

    def __init__(self, queue: "ApprovalQueue") -> None:
        self._queue = queue
        self._draining = False
        self._rerun = False
        self._lock = threading.Lock()

    def drain(self, *, by: str) -> list[PendingAction]:
        """Apply everything currently eligible; return what was applied."""
        with self._lock:
            if self._draining:
                # A drain is already running — ask it to loop again rather
                # than starting a second one over the same actions.
                self._rerun = True
                return []
            self._draining = True
            self._rerun = False

        applied: list[PendingAction] = []
        try:
            while True:
                applied.extend(self._drain_once(by=by))
                with self._lock:
                    if not self._rerun:
                        break
                    self._rerun = False
        finally:
            with self._lock:
                self._draining = False
        return applied

    def _drain_once(self, *, by: str) -> list[PendingAction]:
        applied: list[PendingAction] = []
        enabled = self._queue.auto_tags()
        # Snapshot: applying mutates the queue as we walk it.
        for action in list(self._queue.pending()):
            if not action.eligible_for_auto(enabled):
                # A manual gate. Stop rather than reaching past it.
                break
            # Re-check immediately before applying, in case a concurrent
            # decision already took this one.
            fresh = self._queue.get(action.id)
            if fresh is None or not fresh.is_pending:
                continue
            rule = self._queue.rule_for(fresh.tag)
            try:
                # Attribute to whoever enabled the rule — it runs under their
                # authority, not the agent's.
                self._queue.approve(
                    fresh.id,
                    by=rule.enabled_by if rule else by,
                    auto=True,
                )
            except Exception:
                # Leave it pending for manual handling and stop the drain;
                # never skip ahead of a failure.
                break
            applied.append(fresh)
        return applied


class ApprovalQueue:
    """Holds side-effecting calls until a human decides.

    Thread-safe: the runtime submits from tool threads while a UI resolves
    from another.
    """

    def __init__(
        self,
        *,
        on_change: Callable[[PendingAction], None] | None = None,
    ) -> None:
        self._actions: dict[int, PendingAction] = {}
        self._next_id = 1
        self._rules: dict[str, AutoApproveRule] = {}
        self._lock = threading.RLock()
        self._on_change = on_change
        self._drainer = AutoApprovalDrainer(self)

    # ── submit ───────────────────────────────────────────────────────────

    def submit(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        apply_fn: ApplyFn | None = None,
        contract: ToolContract | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> PendingAction:
        """Queue a call for review. Returns the pending action."""
        resolved = contract or contract_for(tool)
        with self._lock:
            action = PendingAction(
                id=self._next_id,
                tool=tool,
                arguments=dict(arguments),
                contract=resolved,
                title=title or _default_title(tool, arguments),
                description=description or _default_description(tool, arguments),
                apply_fn=apply_fn,
            )
            self._actions[action.id] = action
            self._next_id += 1
        self._notify(action)
        return action

    # ── read ─────────────────────────────────────────────────────────────

    def get(self, action_id: int) -> PendingAction | None:
        with self._lock:
            return self._actions.get(action_id)

    def pending(self) -> list[PendingAction]:
        """Pending actions in submission order — the order a drain walks."""
        with self._lock:
            return [a for a in self._actions.values() if a.is_pending]

    def all(self) -> list[PendingAction]:
        """Every action ever submitted, in order — the audit log."""
        with self._lock:
            return list(self._actions.values())

    def blocking(self) -> list[PendingAction]:
        """Pending actions whose contract says the turn must wait."""
        return [a for a in self.pending() if a.blocks_agent]

    def __len__(self) -> int:
        return len(self.pending())

    def __bool__(self) -> bool:
        # An empty queue is falsy by pending count, not by having ever run.
        return bool(self.pending())

    # ── decide ───────────────────────────────────────────────────────────

    def approve(self, action_id: int, *, by: str = "user", auto: bool = False) -> PendingAction:
        """Approve and **apply** an action.

        A failure during apply marks the action ``FAILED`` and re-raises, so a
        drain can stop rather than silently continuing past a broken effect.
        """
        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                raise KeyError(f"no such action: {action_id}")
            if not action.is_pending:
                return action  # already decided; approving twice is a no-op
            apply_fn = action.apply_fn

        try:
            result = apply_fn() if apply_fn is not None else None
        except Exception as exc:
            with self._lock:
                action.state = ActionState.FAILED
                action.error = str(exc)
                action.resolved_by = by
                action.applied_at = time.time()
            self._notify(action)
            raise

        with self._lock:
            action.state = ActionState.APPROVED
            action.result = result
            action.resolved_by = by
            action.auto_approved = auto
            action.applied_at = time.time()
        self._notify(action)
        return action

    def deny(self, action_id: int, *, by: str = "user", reason: str = "") -> PendingAction:
        """Reject an action. It is never applied and never retried."""
        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                raise KeyError(f"no such action: {action_id}")
            if not action.is_pending:
                return action
            action.state = ActionState.REJECTED
            action.resolved_by = by
            action.error = reason or None
            action.applied_at = time.time()
        self._notify(action)
        return action

    def approve_all(self, *, by: str = "user") -> list[PendingAction]:
        """Approve every pending action, oldest first.

        Stops at the first failure so later effects don't land on top of a
        broken earlier one — the same in-order guarantee the drain gives.
        """
        applied: list[PendingAction] = []
        for action in self.pending():
            try:
                applied.append(self.approve(action.id, by=by))
            except Exception:
                break
        return applied

    def deny_all(self, *, by: str = "user", reason: str = "") -> list[PendingAction]:
        return [self.deny(a.id, by=by, reason=reason) for a in self.pending()]

    # ── auto-approval rules ──────────────────────────────────────────────

    def enable_auto(self, kind: ActionKind | str, *, by: str = "user") -> AutoApproveRule:
        """Always approve this *kind* of action from now on.

        Takes the :class:`ActionKind` so the rule keeps the human-readable
        label alongside the tag it keys on.
        """
        tag = kind.tag if isinstance(kind, ActionKind) else str(kind)
        label = kind.label if isinstance(kind, ActionKind) else str(kind)
        rule = AutoApproveRule(tag, label, by)
        with self._lock:
            self._rules[tag] = rule
        return rule

    def disable_auto(self, kind: ActionKind | str) -> None:
        tag = kind.tag if isinstance(kind, ActionKind) else str(kind)
        with self._lock:
            self._rules.pop(tag, None)

    def auto_tags(self) -> set[str]:
        with self._lock:
            return set(self._rules)

    def rules(self) -> list[AutoApproveRule]:
        with self._lock:
            return list(self._rules.values())

    def rule_for(self, tag: str | None) -> AutoApproveRule | None:
        if tag is None:
            return None
        with self._lock:
            return self._rules.get(tag)

    def drain(self, *, by: str = "user") -> list[PendingAction]:
        """Apply everything an enabled rule covers. See :class:`AutoApprovalDrainer`."""
        return self._drainer.drain(by=by)

    # ── plumbing ─────────────────────────────────────────────────────────

    def _notify(self, action: PendingAction) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(action)
        except Exception:
            # A subscriber must never be able to break the queue.
            pass

    def summary(self) -> dict[str, Any]:
        actions = self.all()
        counts: dict[str, int] = {}
        for action in actions:
            counts[action.state.value] = counts.get(action.state.value, 0) + 1
        return {
            "total": len(actions),
            "pending": len(self.pending()),
            "counts": counts,
            "auto_tags": sorted(self.auto_tags()),
        }


# ── default descriptions ─────────────────────────────────────────────────


def _default_title(tool: str, arguments: dict[str, Any]) -> str:
    """One line, in the Narrator's voice, so the queue reads like the transcript."""
    from shipit_agent.narrate.verbs import summarize

    return summarize(tool, arguments).past_label()


def _default_description(tool: str, arguments: dict[str, Any]) -> str:
    """Markdown detail — everything relevant to the decision, nothing else."""
    if not arguments:
        return f"Run `{tool}` with no arguments."
    lines = [f"Run `{tool}` with:", ""]
    for key, value in arguments.items():
        rendered = str(value)
        if "\n" in rendered or len(rendered) > 120:
            lines.append(f"- **{key}**:\n\n```\n{rendered[:2000]}\n```")
        else:
            lines.append(f"- **{key}**: `{rendered}`")
    return "\n".join(lines)


def coerce_queue(spec: Any) -> ApprovalQueue | None:
    """Normalize an ``approvals=`` argument: a queue, ``True``, or ``None``."""
    if spec is None or spec is False:
        return None
    if isinstance(spec, ApprovalQueue):
        return spec
    if spec is True:
        return ApprovalQueue()
    raise TypeError(f"Unsupported approvals spec: {type(spec)!r}")


def iter_pending(queues: Iterable[ApprovalQueue]) -> list[PendingAction]:
    """Flatten several queues' pending actions, oldest first."""
    actions = [a for queue in queues for a in queue.pending()]
    return sorted(actions, key=lambda a: a.created_at)
