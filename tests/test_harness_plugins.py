"""Claude Code plugins and command hooks (shipit_agent.harness).

Hook commands here are small Python scripts in tmp_path, run with this
interpreter; they only read stdin and write files under tmp_path.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.harness import load_plugin
from shipit_agent.harness.command_hooks import command_hook_matchers
from shipit_agent.sdk.hooks import build_agent_hooks


def _script(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / f"{name}.py"
    path.write_text("import json, os, sys\n" + body)
    return f'"{sys.executable}" "{path}"'


def make_plugin(root: Path, *, manifest: dict[str, Any] | None = None) -> Path:
    plugin = root / "deploy-tools"
    (plugin / "skills" / "greet").mkdir(parents=True)
    (plugin / "skills" / "greet" / "SKILL.md").write_text(
        "---\nname: greet\ndescription: Greet the user warmly.\n---\nSay hello to $ARGUMENTS.\n")
    (plugin / "commands").mkdir()
    (plugin / "commands" / "status.md").write_text("---\ndescription: Status\n---\nShow deploy status for $ARGUMENTS.\n")
    (plugin / "agents").mkdir()
    (plugin / "agents" / "reviewer.md").write_text(
        "---\ndescription: Reviews deploys.\n---\nYou review deploys using ${CLAUDE_PLUGIN_ROOT}/rules.md.\n")
    (plugin / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"files": {"command": "${CLAUDE_PLUGIN_ROOT}/bin/server", "args": ["--root", "${CLAUDE_PLUGIN_ROOT}"]}}}))
    if manifest is not None:
        (plugin / ".claude-plugin").mkdir()
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    return plugin


# -- loading ------------------------------------------------------------------------


def test_a_plugin_namespaces_everything_under_its_name(tmp_path: Path) -> None:
    errors: list[str] = []
    root = make_plugin(tmp_path)
    plugin = load_plugin({"type": "local", "path": str(root)}, cwd=tmp_path, errors=errors)
    assert errors == [] and plugin is not None and plugin.name == "deploy-tools"
    assert [s.id for s in plugin.skills] == ["deploy-tools:greet"]
    assert plugin.commands == {"deploy-tools:status": "Show deploy status for $ARGUMENTS."}
    assert list(plugin.agents) == ["deploy-tools:reviewer"]
    assert str(root) in plugin.agents["deploy-tools:reviewer"].prompt
    [(server, config)] = plugin.mcp_servers.items()
    assert server == "plugin_deploy-tools_files"
    assert config == {"command": f"{root}/bin/server", "args": ["--root", str(root)]}


def test_the_manifest_names_the_plugin_and_can_replace_or_add(tmp_path: Path) -> None:
    root = make_plugin(tmp_path, manifest={
        "name": "ops", "commands": {"about": {"content": "Plugin at ${CLAUDE_PLUGIN_ROOT}"},
                                    "status": {"source": "./commands/status.md"}},
        "skills": ["./extra"], "agents": [],
    })
    (root / "extra" / "wave").mkdir(parents=True)
    (root / "extra" / "wave" / "SKILL.md").write_text("---\nname: wave\ndescription: Wave.\n---\nWave.\n")
    errors: list[str] = []
    plugin = load_plugin(str(root), cwd=tmp_path, errors=errors)
    assert plugin is not None and plugin.name == "ops"
    assert plugin.commands == {"ops:about": f"Plugin at {root}", "ops:status": "Show deploy status for $ARGUMENTS."}
    assert sorted(s.id for s in plugin.skills) == ["ops:greet", "ops:wave"]  # skills add to skills/
    assert plugin.agents == {}  # "agents": [] replaces agents/ with nothing


@pytest.mark.parametrize("spec", [{"type": "local", "path": "missing"}, {"type": "remote", "path": "x"}, ""])
def test_a_plugin_that_cannot_load_is_reported_not_raised(tmp_path: Path, spec: Any) -> None:
    errors: list[str] = []
    assert load_plugin(spec, cwd=tmp_path, errors=errors) is None
    assert len(errors) == 1


def test_bad_manifests_and_escaping_paths_are_reported(tmp_path: Path) -> None:
    root = make_plugin(tmp_path, manifest={"commands": ["../outside.md"]})
    errors: list[str] = []
    load_plugin(str(root), cwd=tmp_path, errors=errors)
    assert any("escapes the plugin directory" in e for e in errors)
    (root / ".claude-plugin" / "plugin.json").write_text("{not json")
    errors = []
    assert load_plugin(str(root), cwd=tmp_path, errors=errors) is None and "not valid JSON" in errors[0]


# -- command hooks ---------------------------------------------------------------------


def _run_pre_tool(matchers: dict[str, Any], arguments: dict[str, Any]) -> Any:
    hooks = build_agent_hooks(matchers, base={"session_id": "s", "cwd": "/", "permission_mode": "default",
                                               "transcript_path": ""})
    return hooks.run_before_tool("note_create", arguments)


def test_exit_2_blocks_with_stderr_and_the_input_arrives_on_stdin(tmp_path: Path) -> None:
    seen = tmp_path / "seen.json"
    command = _script(tmp_path, "guard", f"""
data = json.load(sys.stdin)
open({str(seen)!r}, "w").write(json.dumps(data))
if "secret" in data["tool_input"].get("text", ""):
    print("no secrets in notes", file=sys.stderr); sys.exit(2)
""")
    errors: list[str] = []
    matchers = command_hook_matchers({"PreToolUse": [{"matcher": "note_create", "hooks": [{"type": "command", "command": command}]}]},
                                     project_dir=tmp_path, errors=errors)
    denied = _run_pre_tool(matchers, {"text": "the secret"})
    assert denied.denied and "no secrets in notes" in denied.reason
    assert json.loads(seen.read_text())["tool_name"] == "note_create"
    assert _run_pre_tool(matchers, {"text": "fine"}) is None


def test_exit_0_json_is_the_hooks_output(tmp_path: Path) -> None:
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                     "updatedInput": {"text": "rewritten"}}}
    command = _script(tmp_path, "rewrite", f"print({json.dumps(json.dumps(output))})")
    matchers = command_hook_matchers({"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]},
                                     project_dir=tmp_path, errors=[])
    assert _run_pre_tool(matchers, {"text": "x"}).updated_arguments == {"text": "rewritten"}


def test_other_exits_and_timeouts_do_not_block(tmp_path: Path) -> None:
    failing = _script(tmp_path, "fail", "sys.exit(1)")
    slow = _script(tmp_path, "slow", "import time; time.sleep(5)")
    matchers = command_hook_matchers({"PreToolUse": [{"hooks": [
        {"type": "command", "command": failing}, {"type": "command", "command": slow, "timeout": 0.3}]}]},
        project_dir=tmp_path, errors=[])
    started = time.monotonic()
    assert _run_pre_tool(matchers, {"text": "x"}) is None
    assert time.monotonic() - started < 3


def test_hook_commands_get_the_plugin_root_and_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-do-not-leak")
    dump = tmp_path / "env.json"
    command = _script(tmp_path, "env", f"open({str(dump)!r}, 'w').write(json.dumps(dict(os.environ)))")
    matchers = command_hook_matchers({"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]},
                                     project_dir=tmp_path, plugin_root=tmp_path / "plug", env={"TEAM": "ops"}, errors=[])
    _run_pre_tool(matchers, {})
    env = json.loads(dump.read_text())
    assert env["CLAUDE_PLUGIN_ROOT"] == str(tmp_path / "plug") and env["CLAUDE_PROJECT_DIR"] == str(tmp_path)
    assert env["TEAM"] == "ops" and "ANTHROPIC_API_KEY" not in env


def test_unsupported_events_and_types_are_skipped_and_noted(tmp_path: Path) -> None:
    errors: list[str] = []
    matchers = command_hook_matchers({
        "SessionStart": [{"hooks": [{"type": "command", "command": "true"}]}],
        "PreToolUse": [{"hooks": [{"type": "prompt", "prompt": "Is this safe?"}]}],
    }, project_dir=tmp_path, errors=errors, source="plugin x")
    assert matchers == {}
    assert any("SessionStart" in e for e in errors) and any("'prompt'" in e for e in errors)
