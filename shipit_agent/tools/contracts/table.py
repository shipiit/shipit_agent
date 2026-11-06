"""The contract of every built-in tool."""

from __future__ import annotations

from .types import (
    AGENT_STATE,
    ARTIFACT_WRITE,
    BROWSER_ACT,
    CALENDAR_WRITE,
    CODE_EXEC,
    COMMS_SEND,
    CRM_WRITE,
    DB_WRITE,
    DOC_WRITE,
    FS_WRITE,
    ISSUE_WRITE,
    MEMORY_WRITE,
    NET_WRITE,
    PAYMENT_WRITE,
    SHELL_EXEC,
    VCS_WRITE,
    OBSERVE,
    ToolContract,
    _act,
)

# ── Built-in contracts ───────────────────────────────────────────────────
# `await_decision` reasoning, applied consistently: a call whose *return value*
# the agent will reason over cannot be deferred without lying to it. A call
# whose effect is elsewhere (a message sent, a ticket filed) can.

CONTRACTS: dict[str, ToolContract] = {
    # ── files ────────────────────────────────────────────────────────────
    "read_file": OBSERVE,
    "present_plan": OBSERVE,
    "glob_files": OBSERVE,
    "grep_files": OBSERVE,
    "workspace_files": OBSERVE,
    # Edits are reversible in a repo and the agent reads files back, so they
    # gate — but they are the archetypal "always approve this" case.
    "write_file": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "edit_file": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "multi_edit": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "notebook_edit": _act(FS_WRITE, revert=True, await_decision=True, auto=True),
    "download_file": _act(FS_WRITE, revert=True, await_decision=True),
    # ── execution ────────────────────────────────────────────────────────
    # Never auto-approvable: the argument is arbitrary code, so the tag says
    # nothing about what this particular call does.
    "bash": _act(SHELL_EXEC, await_decision=True, destructive=True),
    "bash_job": _act(SHELL_EXEC, await_decision=True),
    "task_stop": _act(SHELL_EXEC, await_decision=True),
    "run_code": _act(CODE_EXEC, await_decision=True, destructive=True),
    # Same reasoning as run_code: the argument is arbitrary code, so the tag
    # says nothing about what this particular call does. Each env call inside
    # it is separately gated by its own binding's contract.
    "execute_code": _act(CODE_EXEC, await_decision=True, destructive=True),
    "git_ops": _act(VCS_WRITE, await_decision=True),
    # ── apps ─────────────────────────────────────────────────────────────
    # Creating one writes files, and the writes are revertible the same way
    # write_file's are. Running one executes code the agent wrote: never
    # auto-approvable, and never deferrable, because the agent reads what it
    # returned. Wiring a binding changes what an app may reach — an action,
    # even though nothing runs yet.
    "list_blueprints": OBSERVE,
    "create_app": _act(FS_WRITE, await_decision=True, auto=True),
    "set_app_binding": _act(FS_WRITE, await_decision=True, auto=True),
    "use_app": _act(CODE_EXEC, await_decision=True, destructive=True),
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
    "present_file": _act(ARTIFACT_WRITE, auto=True),
    # No revert: it creates a brand-new PNG, it never overwrites existing work,
    # so there is nothing to restore (unlike build_artifact editing a doc).
    "image_generate": _act(ARTIFACT_WRITE, auto=True),
    "text_to_speech": _act(ARTIFACT_WRITE, auto=True),
    "video_generate": _act(ARTIFACT_WRITE, auto=True),
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
