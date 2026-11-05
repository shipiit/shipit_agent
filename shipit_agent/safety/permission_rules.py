"""Permission rules in the Claude Agent SDK's syntax.

A rule is either a bare tool name (a glob) or a tool name with a specifier
in parentheses, which scopes it to matching calls::

    "Bash"                     every bash call
    "mcp__github__*"           every tool from the github MCP server
    "Bash(rm *)"               bash calls whose command matches ``rm *``
    "Bash(npm run test:*)"     bash calls whose command starts with ``npm run test``
    "Edit(src/**)"             writes under ``<root>/src`` (any file-writing tool)
    "Edit(//etc/**)"           writes under ``/etc`` (``//`` is absolute)
    "Edit(/secrets/**)"        writes under ``<root>/secrets`` (one ``/`` is the root)
    "Read(~/.ssh/**)"          reads under the home directory's ``.ssh``
    "WebFetch(domain:x.com)"   fetches from ``x.com``

The SDK's tool names (``Bash``, ``Read``, ``Edit``, ``Write``, ``Glob``,
``Grep``, ``WebFetch``, ...) name shipit's tools; shipit's own names work too.

A compound shell command (``a && b``) is judged part by part: a deny or ask
rule matches when any part matches, an allow rule only when every part does,
so ``Bash(ls *)`` cannot approve ``ls && rm -rf x``. A scoped rule never
matches a call whose argument it cannot read.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from shipit_agent.tools.bash.command_risk import command_segments

__all__ = ["RuleBehavior", "is_scoped", "rule_matches", "rule_names_tool"]

RuleBehavior = Literal["allow", "deny", "ask"]

#: SDK tool names, lower-cased, and the shipit tools each one names.
_SDK_NAMES: dict[str, tuple[str, ...]] = {
    "bash": ("bash",),
    "read": ("read_file", "glob_files", "grep_files"),
    "edit": ("edit_file", "write_file", "multi_edit", "notebook_edit"),
    "write": ("write_file",),
    "multiedit": ("multi_edit",),
    "notebookedit": ("notebook_edit",),
    "glob": ("glob_files",),
    "grep": ("grep_files",),
    "webfetch": ("open_url",),
    "websearch": ("web_search",),
    "todowrite": ("todo",),
    "agent": ("sub_agent",),
    "task": ("sub_agent",),
    "askuserquestion": ("ask_user",),
    "skill": ("load_skill",),
}

#: Which argument a specifier is matched against, by shipit tool.
_COMMAND_TOOLS = frozenset({"bash"})
_PATH_TOOLS = frozenset(
    {"read_file", "glob_files", "grep_files", "edit_file", "write_file", "multi_edit", "notebook_edit"}
)
_URL_TOOLS = frozenset({"open_url"})

_SCOPED = re.compile(r"^\s*([^()\s]+)\s*\((.*)\)\s*$", re.DOTALL)


def is_scoped(rule: str) -> bool:
    """Whether *rule* carries a specifier, as in ``Bash(rm *)``."""
    return _SCOPED.match(rule) is not None


def rule_names_tool(rule: str, tool_name: str) -> bool:
    """Whether *rule* is about *tool_name* at all, ignoring any specifier."""
    scoped = _SCOPED.match(rule)
    name = scoped.group(1) if scoped else rule.strip()
    if fnmatch.fnmatchcase(tool_name, name):
        return True
    return tool_name in _SDK_NAMES.get(name.lower().replace("_", ""), ())


def rule_matches(
    rule: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    root: str | None = None,
    behavior: RuleBehavior = "deny",
) -> bool:
    """Whether *rule* covers this call. *root* anchors relative path rules
    (the working directory when ``None``)."""
    if not rule_names_tool(rule, tool_name):
        return False
    scoped = _SCOPED.match(rule)
    if scoped is None:
        return True
    specifier = scoped.group(2).strip()
    if tool_name in _COMMAND_TOOLS:
        return _command_rule(specifier, arguments.get("command"), behavior)
    if tool_name in _PATH_TOOLS:
        return _path_rule(specifier, arguments.get("path"), root or os.getcwd())
    if tool_name in _URL_TOOLS:
        return _domain_rule(specifier, arguments.get("url"))
    return False


def _command_rule(specifier: str, command: Any, behavior: RuleBehavior) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    parts = command_segments(command)
    if not parts:
        return False
    hits = (_command_matches(specifier, part) for part in parts)
    return all(hits) if behavior == "allow" else any(hits)


def _command_matches(specifier: str, command: str) -> bool:
    if specifier.endswith(":*"):
        return command.startswith(specifier[:-2])
    return fnmatch.fnmatchcase(command, specifier)


def _path_rule(specifier: str, path: Any, root: str) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    target = path if os.path.isabs(path) else os.path.join(root, path)
    return _glob_regex(_anchor(specifier, root)).fullmatch(os.path.normpath(target)) is not None


def _anchor(pattern: str, root: str) -> str:
    """The absolute form of a path pattern, by the SDK's anchoring rules."""
    if pattern.startswith("//"):
        return "/" + pattern[2:]
    if pattern.startswith("~/"):
        return str(Path.home()) + pattern[1:]
    if pattern.startswith("/"):
        return root.rstrip("/") + pattern
    return root.rstrip("/") + "/" + pattern.removeprefix("./")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """``**`` spans directories, ``*`` and ``?`` stay inside one."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out))


def _domain_rule(specifier: str, url: Any) -> bool:
    if not specifier.startswith("domain:") or not isinstance(url, str):
        return False
    host = urlparse(url).hostname
    return host is not None and fnmatch.fnmatchcase(host, specifier[len("domain:"):].strip())
