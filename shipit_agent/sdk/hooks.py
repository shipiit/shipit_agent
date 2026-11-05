"""Hooks the Claude Agent SDK way: ``{"PreToolUse": [HookMatcher(...)]}``.

Each callback is ``async def cb(input_data, tool_use_id, context) -> dict``
(a plain function works too). The input and output dicts follow the SDK's
field names; :func:`build_agent_hooks` turns them into shipit's
:class:`~shipit_agent.safety.hooks.AgentHooks`.

Not carried over: ``continue_: False`` refuses the call (or blocks the
prompt) instead of ending the whole session, and ``tool_use_id`` is ``None``
for ``PreToolUse`` and ``PermissionRequest``.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from shipit_agent.safety.hooks import AgentHooks
from shipit_agent.safety.permission_rules import rule_names_tool

from .tools import run_maybe_async

__all__ = ["HOOK_EVENTS", "HookMatcher", "build_agent_hooks"]

logger = logging.getLogger(__name__)

HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Stop",
    "SubagentStart", "SubagentStop", "PreCompact", "Notification", "PermissionRequest",
)
_TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"})
_FAILED = object()


@dataclass(slots=True)
class HookMatcher:
    """Callbacks for one event, optionally only for matching tools (or sub-agent types)."""

    matcher: str | None = None
    hooks: list[Callable[..., Any]] = field(default_factory=list)
    timeout: float | None = None
    on_failure: Literal["continue", "block"] | None = None


def build_agent_hooks(
    spec: dict[str, list[HookMatcher]], *, base: dict[str, Any], into: AgentHooks | None = None
) -> AgentHooks:
    """Register every matcher in *spec* on an :class:`AgentHooks` (*into*, or a new one).

    *base* holds the fields every input carries: ``session_id``, ``cwd``,
    ``permission_mode``, ``transcript_path``.
    """
    hooks = into if into is not None else AgentHooks()
    for event, matchers in spec.items():
        if event not in HOOK_EVENTS:
            raise ValueError(f"unknown hook event {event!r}; expected one of {', '.join(HOOK_EVENTS)}")
        for matcher in matchers:
            _register(hooks, event, matcher, base)
    return hooks


def _register(hooks: AgentHooks, event: str, matcher: HookMatcher, base: dict[str, Any]) -> None:
    def call(subject: str | None, data: dict[str, Any], tool_use_id: str | None = None) -> list[Any]:
        if subject is not None and not _matches(matcher.matcher, subject):
            return []
        payload = {**base, "hook_event_name": event, **data}
        return [_invoke(cb, payload, tool_use_id, matcher) for cb in matcher.hooks]

    if event == "PreToolUse":
        def pre_tool(name: str, arguments: dict[str, Any]) -> Any:
            return _fold_pre_tool(call(name, {"tool_name": name, "tool_input": dict(arguments), "tool_use_id": None}))
        hooks.on_before_tool(pre_tool)
    elif event == "PostToolUse":
        def post_tool(name: str, arguments: dict[str, Any], result: Any) -> Any:
            data = {"tool_name": name, "tool_input": arguments, "tool_response": result.output,
                    "tool_use_id": result.tool_call_id}
            return _fold_post_tool(call(name, data, result.tool_call_id))
        hooks.on_post_tool_use(post_tool)
    elif event == "PostToolUseFailure":
        def failure(name: str, arguments: dict[str, Any], error: str) -> str:
            outputs = call(name, {"tool_name": name, "tool_input": arguments, "error": error})
            return "\n".join(_context(o) for o in outputs if _context(o))
        hooks.on_post_tool_failure(failure)
    elif event == "PermissionRequest":
        def request(name: str, arguments: dict[str, Any], reason: str) -> Any:
            return _fold_permission_request(call(name, {"tool_name": name, "tool_input": dict(arguments)}))
        hooks.on_permission_request(request)
    elif event == "UserPromptSubmit":
        def prompt(text: str) -> Any:
            outputs = call(None, {"prompt": text})
            if any(_blocks(o) for o in outputs):
                return {"decision": "deny", "reason": next(_reason(o) for o in outputs if _blocks(o))}
            extra = [_context(o) for o in outputs if _context(o)]
            return "\n\n".join([text, *extra]) if extra else None
        hooks.on_user_prompt(prompt)
    elif event == "Stop":
        def stop(answer: str) -> str | None:
            outputs = call(None, {"stop_hook_active": False})
            return next((_reason(o) or "Keep going." for o in outputs if _blocks(o)), None)
        hooks.on_stop(stop)
    elif event == "SubagentStart":
        def subagent_start(agent_type: str, task: str) -> Any:
            outputs = call(agent_type, {"agent_id": "", "agent_type": agent_type})
            if any(_blocks(o) for o in outputs):
                return False
            return "\n".join(_context(o) for o in outputs if _context(o)) or None
        hooks.on_subagent_start(subagent_start)
    elif event == "SubagentStop":
        def subagent_stop(agent_type: str, task: str, output: str, error: str) -> None:
            call(agent_type, {"agent_id": "", "agent_type": agent_type, "agent_transcript_path": "",
                              "stop_hook_active": False})
        hooks.on_subagent_stop(subagent_stop)
    elif event == "PreCompact":
        def pre_compact(messages: list[Any], info: dict[str, Any]) -> None:
            call(None, {"trigger": "auto", "custom_instructions": None})
        hooks.on_pre_compact(pre_compact)
    elif event == "Notification":
        def notification(message: str, kind: str) -> None:
            call(None, {"message": message, "notification_type": kind})
        hooks.on_notification(notification)


def _matches(matcher: str | None, subject: str) -> bool:
    if not matcher or matcher == "*":
        return True
    alternatives = [part.strip() for part in matcher.split("|") if part.strip()]
    if any(rule_names_tool(part, subject) for part in alternatives):
        return True
    try:
        return re.fullmatch(matcher, subject) is not None
    except re.error:
        return False


def _invoke(cb: Callable[..., Any], payload: dict[str, Any], tool_use_id: str | None,
            matcher: HookMatcher) -> Any:
    """One callback's output dict, or ``_FAILED`` when it raised or timed out."""
    context = {"signal": None}
    try:
        if matcher.timeout is None:
            output = run_maybe_async(cb, payload, tool_use_id, context)
        else:
            # Not a `with` block: leaving one waits for the callback, which is
            # exactly what the timeout is there to stop.
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(contextvars.copy_context().run, run_maybe_async,
                                     cb, payload, tool_use_id, context)
                output = future.result(timeout=matcher.timeout)
            finally:
                pool.shutdown(wait=False)
    except Exception:
        logger.warning("hook %s failed for %s", getattr(cb, "__name__", cb),
                       payload.get("hook_event_name"), exc_info=True)
        return _FAILED if matcher.on_failure == "block" else {}
    return output if isinstance(output, dict) else {}


def _specific(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    specific = output.get("hookSpecificOutput") or output.get("hook_specific_output") or {}
    return specific if isinstance(specific, dict) else {}


def _blocks(output: Any) -> bool:
    if output is _FAILED:
        return True
    return isinstance(output, dict) and (
        output.get("decision") == "block" or output.get("continue_", output.get("continue")) is False
    )


def _reason(output: Any) -> str:
    if output is _FAILED:
        return "a hook failed and is set to block on failure"
    return str(output.get("reason") or output.get("stopReason") or _specific(output).get(
        "permissionDecisionReason") or "")


def _context(output: Any) -> str:
    return "" if output is _FAILED else str(_specific(output).get("additionalContext") or "").strip()


def _fold_pre_tool(outputs: list[Any]) -> dict[str, Any] | None:
    decision: dict[str, Any] | None = None
    for output in outputs:
        specific = _specific(output)
        verdict = specific.get("permissionDecision")
        if _blocks(output) or verdict == "deny":
            return {"decision": "deny", "reason": _reason(output) or "denied by a hook"}
        if verdict == "ask":
            decision = {"decision": "ask", "reason": _reason(output) or "a hook asked for approval"}
        elif verdict == "allow" and (decision is None or decision["decision"] != "ask"):
            decision = {"decision": "allow", "reason": _reason(output),
                        "updated_arguments": specific.get("updatedInput")}
    return decision


def _fold_post_tool(outputs: list[Any]) -> dict[str, Any] | None:
    folded: dict[str, Any] = {}
    for output in outputs:
        specific = _specific(output)
        replaced = specific.get("updatedToolOutput", specific.get("updatedMCPToolOutput"))
        if replaced is not None:
            folded["updated_output"] = replaced if isinstance(replaced, str) else str(replaced)
        if _context(output):
            folded["additional_context"] = "\n".join(filter(None, [folded.get("additional_context"), _context(output)]))
    return folded or None


def _fold_permission_request(outputs: list[Any]) -> dict[str, Any] | None:
    for output in outputs:
        if output is _FAILED:
            return {"decision": "deny", "reason": _reason(output)}
        decision = _specific(output).get("decision")
        if isinstance(decision, dict) and decision.get("behavior") in ("allow", "deny"):
            return {"decision": decision["behavior"], "reason": str(decision.get("message") or ""),
                    "updated_arguments": decision.get("updatedInput")}
    return None
