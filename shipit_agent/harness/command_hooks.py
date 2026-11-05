"""Claude Code command hooks: shell commands that read the hook input on stdin.

    {"hooks": {"PreToolUse": [{"matcher": "Bash",
                               "hooks": [{"type": "command", "command": "./check.sh", "timeout": 30}]}]}}

As in Claude Code, a command gets the hook input as JSON on stdin and:

- exit 0: stdout, if it is one JSON object, is the hook's output; plain
  text is added as context for ``UserPromptSubmit`` and ignored otherwise;
- exit 2: blocks, with stderr as the reason (a tool call is refused, a
  prompt is blocked, a stop is turned back; after a tool ran, stderr is
  shown to the model; ignored for notifications and permission requests);
- any other exit, or a timeout, is logged and the run carries on.

The command runs with a minimal environment (no secrets from this
process), plus ``CLAUDE_PROJECT_DIR``, ``CLAUDE_PLUGIN_ROOT`` for plugin
hooks, and the ``env`` of the settings that declared it.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from shipit_agent.sdk.hooks import HOOK_EVENTS, HookMatcher
from shipit_agent.tools.subprocess_env import build_tool_env

__all__ = ["command_hook_matchers"]

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600.0
_EVENT_TIMEOUTS = {"UserPromptSubmit": 30.0}


def command_hook_matchers(
    config: Mapping[str, Any],
    *,
    project_dir: Path,
    plugin_root: Path | None = None,
    env: Mapping[str, str] | None = None,
    source: str = "settings",
    errors: list[str],
) -> dict[str, list[HookMatcher]]:
    """``{event: [HookMatcher]}`` for an event map, as in settings ``"hooks"``.

    Events and hook types shipit cannot run are skipped with a note in
    *errors*, so one plugin's newer hook does not stop the whole run.
    """
    found: dict[str, list[HookMatcher]] = {}
    for event, groups in config.items():
        if event not in HOOK_EVENTS:
            errors.append(f"{source}: hook event {event!r} is not supported; skipped")
            continue
        for group in groups if isinstance(groups, list) else []:
            callbacks = []
            for spec in group.get("hooks") or [] if isinstance(group, dict) else []:
                if not isinstance(spec, dict) or spec.get("type", "command") != "command" or not spec.get("command"):
                    kind = spec.get("type") if isinstance(spec, dict) else type(spec).__name__
                    errors.append(f"{source}: {event} hook of type {kind!r} is not supported; skipped")
                    continue
                timeout = float(spec.get("timeout") or _EVENT_TIMEOUTS.get(event, _DEFAULT_TIMEOUT))
                child_env = _environment(project_dir, plugin_root, env)
                callbacks.append(_command_callback(str(spec["command"]), event, timeout, project_dir, child_env))
            if callbacks:
                found.setdefault(event, []).append(HookMatcher(group.get("matcher") or None, callbacks))
    return found


def _environment(project_dir: Path, plugin_root: Path | None, env: Mapping[str, str] | None) -> dict[str, str]:
    extra = {"CLAUDE_PROJECT_DIR": str(project_dir), **dict(env or {})}
    if plugin_root is not None:
        extra["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    return build_tool_env(extra_env=extra)


def _command_callback(
    command: str, event: str, timeout: float, cwd: Path, env: dict[str, str]
) -> Callable[..., dict[str, Any]]:
    def run(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        try:
            done = subprocess.run(
                ["/bin/sh", "-c", command], input=json.dumps(input_data, default=str),
                capture_output=True, text=True, cwd=str(cwd), env=env, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run kills the process when the timeout expires.
            logger.warning("%s hook timed out after %ss: %s", event, timeout, command)
            return {}
        except OSError as error:
            logger.warning("%s hook could not start (%s): %s", event, error, command)
            return {}
        if done.returncode == 0:
            return _from_stdout(event, done.stdout)
        if done.returncode == 2:
            return _blocking(event, done.stderr.strip() or f"{event} hook blocked this")
        logger.warning("%s hook exited %s: %s", event, done.returncode, (done.stderr.strip().splitlines() or [""])[0])
        return {}

    run.__name__ = f"command_hook[{command[:40]}]"
    return run


def _from_stdout(event: str, stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if event == "UserPromptSubmit":
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
    return {}


def _blocking(event: str, reason: str) -> dict[str, Any]:
    if event == "PreToolUse":
        return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}
    if event in ("UserPromptSubmit", "Stop", "SubagentStop"):
        return {"decision": "block", "reason": reason}
    if event in ("PostToolUse", "PostToolUseFailure"):
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": reason}}
    # Notification, PermissionRequest, SubagentStart, PreCompact: exit 2 is not a decision here.
    return {}
