"""Scoped permission rules, as the Claude Agent SDK writes them.

``Bash(rm *)`` scopes a rule to matching calls; a bare ``Bash`` names the
whole tool. SDK tool names (``Bash``, ``Edit``, ``Read``, ``WebFetch``) and
shipit's own (``bash``, ``edit_file``) both work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.safety.permission_rules import rule_matches
from shipit_agent.safety.permissions import PermissionDecision, PermissionEngine

ROOT = "/work/repo"


def _bash(command: str) -> dict[str, str]:
    return {"command": command}


# -- the rule forms ------------------------------------------------------------


@pytest.mark.parametrize(
    "rule,tool",
    [("bash", "bash"), ("Bash", "bash"), ("mcp__github__*", "mcp__github__get_issue"),
     ("*", "anything"), ("Edit", "edit_file"), ("Edit", "write_file"), ("Read", "read_file")],
)
def test_a_bare_rule_names_the_whole_tool(rule: str, tool: str) -> None:
    assert rule_matches(rule, tool, {}, root=ROOT)


def test_a_bare_rule_does_not_match_another_tool() -> None:
    assert not rule_matches("Bash", "read_file", {}, root=ROOT)


def test_a_command_rule_matches_the_command_as_written() -> None:
    assert rule_matches("Bash(rm *)", "bash", _bash("rm -rf build"), root=ROOT)
    assert not rule_matches("Bash(rm *)", "bash", _bash("ls -la"), root=ROOT)
    assert not rule_matches("Bash(rm *)", "bash", _bash("/bin/rm -rf build"), root=ROOT)


def test_the_colon_star_form_is_a_prefix() -> None:
    rule = "Bash(npm run test:*)"
    assert rule_matches(rule, "bash", _bash("npm run test"), root=ROOT)
    assert rule_matches(rule, "bash", _bash("npm run test -- --watch"), root=ROOT)
    assert not rule_matches(rule, "bash", _bash("npm run build"), root=ROOT)


def test_a_deny_matches_any_part_of_a_compound_command() -> None:
    command = _bash("cd build && rm -rf dist")
    assert rule_matches("Bash(rm *)", "bash", command, root=ROOT, behavior="deny")


def test_an_allow_needs_every_part_of_a_compound_command() -> None:
    assert rule_matches("Bash(ls *)", "bash", _bash("ls -la"), root=ROOT, behavior="allow")
    assert not rule_matches(
        "Bash(ls *)", "bash", _bash("ls -la && rm -rf x"), root=ROOT, behavior="allow"
    )


@pytest.mark.parametrize("tool", ["edit_file", "write_file", "multi_edit", "notebook_edit"])
def test_an_edit_rule_covers_every_tool_that_writes_files(tool: str) -> None:
    assert rule_matches("Edit(src/**)", tool, {"path": "src/app/main.py"}, root=ROOT)
    assert not rule_matches("Edit(src/**)", tool, {"path": "docs/index.md"}, root=ROOT)


def test_path_rules_anchor_the_way_the_sdk_does() -> None:
    # // is absolute, a single / is inside the root, ~/ is the home directory.
    assert rule_matches("Edit(//etc/**)", "write_file", {"path": "/etc/hosts"}, root=ROOT)
    assert rule_matches(
        "Edit(/secrets/**)", "write_file", {"path": f"{ROOT}/secrets/key"}, root=ROOT
    )
    assert not rule_matches(
        "Edit(/secrets/**)", "write_file", {"path": "/secrets/key"}, root=ROOT
    )
    home_key = str(Path.home() / ".ssh" / "id_rsa")
    assert rule_matches("Read(~/.ssh/**)", "read_file", {"path": home_key}, root=ROOT)


def test_a_single_star_stays_inside_one_directory() -> None:
    assert rule_matches("Edit(src/*.py)", "edit_file", {"path": "src/a.py"}, root=ROOT)
    assert not rule_matches("Edit(src/*.py)", "edit_file", {"path": "src/x/a.py"}, root=ROOT)


def test_a_relative_path_cannot_escape_the_rule_with_dot_dot() -> None:
    assert not rule_matches(
        "Edit(src/**)", "edit_file", {"path": "src/../secrets/key"}, root=ROOT
    )


def test_a_domain_rule_matches_the_host() -> None:
    rule = "WebFetch(domain:example.com)"
    assert rule_matches(rule, "open_url", {"url": "https://example.com/a"}, root=ROOT)
    assert not rule_matches(rule, "open_url", {"url": "https://evil.com/?q=example.com"}, root=ROOT)


@pytest.mark.parametrize("arguments", [{}, {"command": None}, {"command": 7}, {"path": ""}])
def test_a_scoped_rule_never_matches_a_call_it_cannot_read(arguments: dict) -> None:
    assert not rule_matches("Bash(rm *)", "bash", arguments, root=ROOT)
    assert not rule_matches("Edit(src/**)", "edit_file", arguments, root=ROOT)


def test_a_scoped_rule_on_an_unknown_tool_matches_nothing() -> None:
    assert not rule_matches("Frobnicate(x)", "frobnicate", {"x": "x"}, root=ROOT)


# -- the engine ----------------------------------------------------------------


def test_a_scoped_deny_holds_even_in_bypass_mode() -> None:
    engine = PermissionEngine(mode="bypassPermissions", deny=["Bash(rm *)"], root=ROOT)
    assert engine.check("bash", _bash("rm -rf /tmp/x")).denied
    assert engine.check("bash", _bash("ls")).allowed


def test_a_scoped_deny_keeps_the_tool_but_a_bare_deny_removes_it() -> None:
    assert PermissionEngine(deny=["Bash(rm *)"], root=ROOT).discoverable("bash")
    assert not PermissionEngine(deny=["Bash"], root=ROOT).discoverable("bash")


def test_a_scoped_allow_approves_only_matching_calls() -> None:
    engine = PermissionEngine(
        allow=["Bash(npm test *)"], default_decision=PermissionDecision.DENY, root=ROOT
    )
    assert engine.check("bash", _bash("npm test --ci")).allowed
    assert engine.check("bash", _bash("npm publish")).denied


def test_a_scoped_ask_routes_matching_calls_to_a_human() -> None:
    engine = PermissionEngine(ask=["Edit(//etc/**)"], root=ROOT)
    assert engine.check("write_file", {"path": "/etc/hosts"}).needs_approval
    assert engine.check("write_file", {"path": f"{ROOT}/a.txt"}).allowed


def test_bare_rules_behave_as_before() -> None:
    engine = PermissionEngine(deny=["sql"], allow=["read_*"], default_decision=PermissionDecision.DENY)
    assert engine.check("sql", {}).denied
    assert engine.check("read_file", {"path": "x"}).allowed
    assert engine.check("write_file", {"path": "x"}).denied


def test_only_hidden_rules_take_a_tool_out_of_the_run() -> None:
    # A bare deny keeps the tool and refuses each call (a tool_denied event);
    # the Agent's disallowed_tools bare names are what hide a tool.
    assert not PermissionEngine(deny=["bash"]).removes("bash")
    assert PermissionEngine(hidden=["Bash"]).removes("bash")
    assert PermissionEngine(hidden=["mcp__*"]).removes("mcp__srv__echo")
