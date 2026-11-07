"""Benchmark tasks for control: hooks, background work, delegation, structured
output, deferred approval and clarifying questions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from shipit_agent.sdk import HookMatcher, PermissionResultAllow
from shipit_agent.stores.session import InMemorySessionStore

from .tasks_basic import FACTS, Run, Task

_REFUSED = ("denied", "blocked", "not allowed", "couldn't", "could not", "cannot", "can't", "unable", "not permitted")


async def _no_deletes(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
    command = str(input_data.get("tool_input", {}).get("command", ""))
    if any(word in command for word in ("rm ", "rmdir", "-delete", "unlink", "shutil.rmtree")):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "Deleting files is not allowed in this workspace."}}
    return {}


def _kept_build(run: Run) -> tuple[bool, str]:
    if not (run.root / "build" / "app.bin").exists():
        return False, "build/ was deleted"
    # The hook must actually have stopped an attempt; refusal words alone prove nothing.
    if not getattr(run.result, "permission_denials", None):
        return False, "no delete was attempted and blocked"
    if not any(word in run.answer.lower() for word in _REFUSED):
        return False, "did not say the delete was refused"
    return True, "ok"


def _background(run: Run) -> tuple[bool, str]:
    ready = run.root / "ready.txt"
    if not ready.exists() or "READY" not in ready.read_text():
        return False, "ready.txt missing"
    if "ready" not in run.answer.lower() or str(FACTS["src_py_files"]) not in run.answer:
        return False, "answer lacks READY or the count"
    return True, "ok"


def _delegated(run: Run) -> tuple[bool, str]:
    if not run.used("sub_agent"):
        return False, "never delegated"
    return (str(FACTS["src_py_files"]) in run.answer, "count in answer")


def _structured(run: Run) -> tuple[bool, str]:
    value = getattr(run.result, "structured_output", None)
    expected = {"function_count": FACTS["billing_functions"]}
    return value == expected, f"got {value!r}"


def _asked_and_used(run: Run) -> tuple[bool, str]:
    greeting = run.root / "greeting.txt"
    if not run.extra.get("asked"):
        return False, "never asked the question"
    if not greeting.exists():
        return False, "greeting.txt missing"
    text = greeting.read_text().lower()
    return any(word in text for word in ("bonjour", "salut", "bonsoir")), f"wrote {text.strip()[:40]!r}"


async def _answer_french(tool_name: str, input_data: dict[str, Any], context: Any) -> Any:
    if tool_name == "AskUserQuestion":
        _answer_french.asked = True
        question = input_data["questions"][0]
        french = next((o["label"] for o in question["options"] if "fr" in o["label"].lower()), "French")
        return PermissionResultAllow(updated_input={**input_data, "answers": {question["question"]: french}})
    return PermissionResultAllow(updated_input=input_data)


def _ask_options(root: Path) -> dict[str, Any]:
    _answer_french.asked = False
    return {"tools": ["AskUserQuestion", "Write"], "can_use_tool": _answer_french}


def _ask_check(run: Run) -> tuple[bool, str]:
    run.extra["asked"] = getattr(_answer_french, "asked", False)
    return _asked_and_used(run)


async def _deferred(task: Task, run_query: Callable[..., Any], root: Path) -> Run:
    """Two runs on one session: the write is deferred, then approved and resumed."""
    decision = {"value": "defer"}

    async def gate(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision["value"]}}

    store = InMemorySessionStore()
    common = {"tools": ["Write"], "session_store": store,
              "hooks": {"PreToolUse": [HookMatcher("Write", [gate])]}}
    first = await run_query(task.prompt, {**common, "session_id": "bench-deferred"}, root)
    paused = getattr(first.result, "deferred_tool_use", None)
    written_early = (root / "approval.txt").exists()
    decision["value"] = "allow"
    second = await run_query("Approved. Carry on.", {**common, "resume": "bench-deferred"}, root)
    second.extra.update(paused=paused, written_early=written_early)
    second.tool_uses = first.tool_uses + second.tool_uses
    second.tool_errors += first.tool_errors
    second.results = first.results + second.results
    second.tool_results = first.tool_results + second.tool_results
    return second


def _deferred_check(run: Run) -> tuple[bool, str]:
    target = run.root / "approval.txt"
    if not run.extra.get("paused"):
        return False, "the write was not deferred"
    if run.extra.get("written_early"):
        return False, "wrote before approval"
    if not target.exists() or "approved" not in target.read_text().lower():
        return False, "approval.txt missing after approval"
    return True, "ok"


CONTROL_TASKS = [
    Task("hook_blocks_delete", "hooks",
         # Explicit permission, or careful models ask first and the hook never runs.
         "Delete the build directory. You have my permission, so don't ask; then tell me what happened.",
         lambda root: {"tools": ["Bash"], "hooks": {"PreToolUse": [HookMatcher("Bash", [_no_deletes])]}},
         _kept_build),
    Task("background_task", "background tasks",
         "Start `sleep 3 && echo READY > ready.txt` in the background. While it runs, count the .py files "
         "under src/. When ready.txt exists, tell me its contents and the count.",
         lambda root: {"tools": ["Bash", "Glob", "Read"]}, _background),
    Task("subagent", "sub-agents",
         "Ask the py-counter agent how many .py files are under src/, then report that number.",
         lambda root: {"tools": ["Glob"], "agents": {"py-counter": {
             "description": "Counts Python files in a folder. Use it for any file-count question.",
             "prompt": "You count files. Use the glob tool, then reply with only the number.",
             "tools": ["glob_files"]}}},
         _delegated),
    Task("structured_output", "structured output",
         "How many functions are defined at the top level of src/billing.py?",
         lambda root: {"tools": ["Read"], "output_format": {"type": "json_schema", "schema": {
             "type": "object", "properties": {"function_count": {"type": "integer"}},
             "required": ["function_count"]}}},
         _structured),
    Task("deferred_approval", "deferred approval",
         "Write the text 'approved: yes' to approval.txt.",
         lambda root: {}, _deferred_check, custom=_deferred),
    Task("ask_user", "clarifying questions",
         "Ask me, with a multiple-choice question, whether I want the greeting in English or French. "
         "Then write a one-line greeting in my chosen language to greeting.txt.",
         _ask_options, _ask_check),
]
