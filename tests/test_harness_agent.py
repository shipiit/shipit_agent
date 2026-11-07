"""Settings files and plugins on a real agent, and through the SDK."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.harness import Harness, load_settings_sources
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, SystemMessage, query

from test_harness_plugins import make_plugin


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self, *calls: tuple[str, dict[str, Any]]) -> None:
        self.calls = list(calls)
        self.prompts: list[str] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.prompts.append(str(next(m.content for m in reversed(messages) if m.role == "user")))
        if self.calls:
            name, arguments = self.calls.pop(0)
            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments)])
        return LLMResponse(content="done")


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


NOTE = FunctionTool.from_callable(_note, name="note_create")


def _settings(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# -- settings files ----------------------------------------------------------------------


def test_nothing_is_read_unless_a_source_is_named(tmp_path: Path) -> None:
    _settings(tmp_path / ".claude" / "settings.json", {"permissions": {"deny": ["Bash"]}})
    assert load_settings_sources(None, tmp_path).deny == []
    assert load_settings_sources(["project"], tmp_path).deny == ["Bash"]


def test_permission_lists_add_up_and_the_local_mode_wins(tmp_path: Path) -> None:
    _settings(tmp_path / ".claude" / "settings.json",
              {"permissions": {"allow": ["Read"], "deny": ["Bash(rm *)"], "defaultMode": "plan"}, "env": {"A": "1"}})
    _settings(tmp_path / ".claude" / "settings.local.json",
              {"permissions": {"allow": ["Grep", "Read"], "defaultMode": "acceptEdits"}, "env": {"A": "2"}})
    merged = load_settings_sources(["project", "local"], tmp_path)
    assert merged.allow == ["Read", "Grep"] and merged.deny == ["Bash(rm *)"]
    assert merged.default_mode == "acceptEdits" and merged.env == {"A": "2"}


def test_a_broken_settings_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{oops")
    assert "not valid JSON" in load_settings_sources(["project"], tmp_path).errors[0]


def test_a_settings_hook_blocks_a_call_on_the_agent(tmp_path: Path) -> None:
    script = tmp_path / "deny.py"
    script.write_text("import sys\nprint('notes are frozen', file=sys.stderr)\nsys.exit(2)\n")
    _settings(tmp_path / ".claude" / "settings.json", {"hooks": {"PreToolUse": [
        {"matcher": "note_create", "hooks": [{"type": "command", "command": f'"{sys.executable}" "{script}"'}]}]}})
    harness = Harness.load(tmp_path, setting_sources=["project"])
    result = Agent(llm=_Model(("note_create", {"text": "x"})), tools=[NOTE], harness=harness,
                   project_root=tmp_path).run("go")
    assert not any(str(r.output).startswith("noted:") for r in result.tool_results)
    assert result.permission_denials and "notes are frozen" in json.dumps(
        [e.payload for e in result.events if e.type == "tool_denied"])


# -- plugins on an agent --------------------------------------------------------------------


@pytest.fixture
def plugin_harness(tmp_path: Path) -> Harness:
    make_plugin(tmp_path)
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "triage.md").write_text("Triage issue $1 with priority $2.")
    return Harness.load(tmp_path, plugins=[{"type": "local", "path": "deploy-tools"}], setting_sources=["project"])


def test_plugin_commands_and_skills_expand_from_a_slash(plugin_harness: Harness, tmp_path: Path) -> None:
    llm = _Model()
    agent = Agent(llm=llm, harness=plugin_harness, project_root=tmp_path)
    agent.run("/deploy-tools:status staging")
    agent.run("/deploy-tools:greet Ada")
    agent.run("/triage 42 high")
    assert "Show deploy status for staging." in llm.prompts[0]
    assert "Say hello to" in llm.prompts[1] and "Ada" in llm.prompts[1]
    assert "Triage issue 42 with priority high." in llm.prompts[2]


def test_plugin_skills_are_listed_and_agents_attached(plugin_harness: Harness, tmp_path: Path) -> None:
    agent = Agent(llm=_Model(), harness=plugin_harness, project_root=tmp_path)
    assert "deploy-tools:greet" in [s.id for s in agent._listed_skills()]
    assert "deploy-tools:reviewer" in agent.agents
    assert [m.name for m in agent.mcps] == ["plugin_deploy-tools_files"]


def test_cloning_an_agent_does_not_register_hooks_twice(tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    script = tmp_path / "count.py"
    script.write_text(f"open({str(calls)!r}, 'a').write('x')\n")
    _settings(tmp_path / ".claude" / "settings.json", {"hooks": {"PreToolUse": [
        {"hooks": [{"type": "command", "command": f'"{sys.executable}" "{script}"'}]}]}})
    agent = Agent(llm=_Model(("note_create", {"text": "x"})), tools=[NOTE],
                  harness=Harness.load(tmp_path, setting_sources=["project"]), project_root=tmp_path)
    agent.clone().clone().run("go")
    assert calls.read_text() == "x"


# -- through the SDK ---------------------------------------------------------------------------


def test_the_init_message_lists_plugins_skills_and_commands(tmp_path: Path) -> None:
    make_plugin(tmp_path)

    async def run() -> list[Any]:
        options = AgentOptions(llm=_Model(), cwd=tmp_path, tools=[],
                               plugins=[{"type": "local", "path": "deploy-tools"}, {"type": "local", "path": "gone"}])
        return [m async for m in query(prompt="hi", options=options)]

    init = asyncio.run(run())[0]
    assert isinstance(init, SystemMessage) and init.subtype == "init"
    assert init.data["plugins"] == [{"name": "deploy-tools", "path": str((tmp_path / "deploy-tools").resolve())}]
    assert init.data["skills"] == ["deploy-tools:greet"]
    assert {"deploy-tools:status", "deploy-tools:greet"} <= set(init.data["slash_commands"])
    assert any("gone" in error for error in init.data["plugin_errors"])
