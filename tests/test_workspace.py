"""Tests for the SHIPIT Workspace — project memory, slash commands, settings."""

from __future__ import annotations

from typing import Any

from shipit_agent import (
    Agent,
    FunctionTool,
    PermissionEngine,
    discover_commands,
    expand_command,
    load_project_memory,
    load_settings,
)
from shipit_agent.llms import ShipitLLM
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


# ---------------------------------------------------------------------------
# Project memory
# ---------------------------------------------------------------------------


class TestProjectMemory:
    def test_loads_shipit_md(self, tmp_path) -> None:
        (tmp_path / "SHIPIT.md").write_text("Always be terse.", encoding="utf-8")
        mem = load_project_memory(tmp_path, include_user=False)
        assert "Always be terse." in mem
        assert "Project instructions" in mem

    def test_loads_agents_md(self, tmp_path) -> None:
        (tmp_path / "AGENTS.md").write_text("Use snake_case.", encoding="utf-8")
        assert "Use snake_case." in load_project_memory(tmp_path, include_user=False)

    def test_dot_shipit_location(self, tmp_path) -> None:
        (tmp_path / ".shipit").mkdir()
        (tmp_path / ".shipit" / "SHIPIT.md").write_text("Rule X", encoding="utf-8")
        assert "Rule X" in load_project_memory(tmp_path, include_user=False)

    def test_resolves_at_imports(self, tmp_path) -> None:
        (tmp_path / "style.md").write_text("Prefer dataclasses.", encoding="utf-8")
        (tmp_path / "SHIPIT.md").write_text("Be terse.\n@style.md", encoding="utf-8")
        mem = load_project_memory(tmp_path, include_user=False)
        assert "Be terse." in mem and "Prefer dataclasses." in mem

    def test_empty_when_no_files(self, tmp_path) -> None:
        assert load_project_memory(tmp_path, include_user=False) == ""


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def _write_command(root, name: str, body: str) -> None:
    d = root / ".shipit" / "commands"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body, encoding="utf-8")


class TestSlashCommands:
    def test_discover(self, tmp_path) -> None:
        _write_command(tmp_path, "review", "Review the code.")
        _write_command(tmp_path, "test", "Write tests.")
        assert set(discover_commands(tmp_path)) == {"review", "test"}

    def test_expand_with_arguments(self, tmp_path) -> None:
        _write_command(tmp_path, "greet", "Say hello to $ARGUMENTS.")
        assert expand_command(tmp_path, "/greet Ada") == "Say hello to Ada."

    def test_positional_args(self, tmp_path) -> None:
        _write_command(tmp_path, "diff", "Compare $1 and $2.")
        assert expand_command(tmp_path, "/diff a.py b.py") == "Compare a.py and b.py."

    def test_strips_frontmatter(self, tmp_path) -> None:
        _write_command(tmp_path, "x", "---\ndesc: y\n---\nDo the thing.")
        assert expand_command(tmp_path, "/x") == "Do the thing."

    def test_unknown_command_returns_none(self, tmp_path) -> None:
        assert expand_command(tmp_path, "/nope") is None

    def test_non_command_passthrough(self, tmp_path) -> None:
        assert expand_command(tmp_path, "hello there") is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _write_settings(root, data: str) -> None:
    d = root / ".shipit"
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(data, encoding="utf-8")


class TestSettings:
    def test_parses_permissions(self, tmp_path) -> None:
        _write_settings(tmp_path, '{"permissions": {"deny": ["bash"], "ask": ["sql"]}}')
        s = load_settings(tmp_path, include_user=False)
        assert s.deny == ["bash"] and s.ask == ["sql"]

    def test_to_permission_engine(self, tmp_path) -> None:
        _write_settings(tmp_path, '{"permissions": {"deny": ["bash"]}}')
        engine = load_settings(tmp_path, include_user=False).to_permission_engine()
        assert isinstance(engine, PermissionEngine)
        assert engine.check("bash", {}).denied

    def test_default_settings_no_engine(self, tmp_path) -> None:
        assert load_settings(tmp_path, include_user=False).to_permission_engine() is None

    def test_model_and_env(self, tmp_path) -> None:
        _write_settings(tmp_path, '{"model": "gpt-4o", "env": {"FOO": "bar"}}')
        s = load_settings(tmp_path, include_user=False)
        assert s.model == "gpt-4o" and s.env == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------


class _CallThenDone:
    def __init__(self, tool_name: str):
        self._tool = tool_name
        self._n = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self._n += 1
        if self._n == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name=self._tool, arguments={})])
        return LLMResponse(content="done")


class TestAgentIntegration:
    def test_project_memory_in_prompt(self, tmp_path) -> None:
        (tmp_path / "SHIPIT.md").write_text("Always answer in haiku.", encoding="utf-8")
        agent = Agent(llm=ShipitLLM(), project_root=str(tmp_path), auto_use_skills=False)
        assert "Always answer in haiku." in agent.prompt

    def test_auto_project_memory_off(self, tmp_path) -> None:
        (tmp_path / "SHIPIT.md").write_text("secret rule", encoding="utf-8")
        agent = Agent(
            llm=ShipitLLM(),
            project_root=str(tmp_path),
            auto_project_memory=False,
            auto_use_skills=False,
        )
        assert "secret rule" not in agent.prompt

    def test_slash_command_expands_on_run(self, tmp_path) -> None:
        _write_command(tmp_path, "greet", "Say hello to $ARGUMENTS now.")
        agent = Agent(llm=ShipitLLM(), project_root=str(tmp_path), auto_use_skills=False)
        # ShipitLLM echoes the last user message — which is the expanded command.
        out = agent.run("/greet Ada").output
        assert "Say hello to Ada now." in out

    def test_for_project_applies_settings_permissions(self, tmp_path) -> None:
        _write_settings(tmp_path, '{"permissions": {"deny": ["bash"]}}')
        ran: list[str] = []

        def _bash(**kw: Any) -> str:
            ran.append("bash")
            return "ran"

        agent = Agent.for_project(
            llm=_CallThenDone("bash"),
            project_root=str(tmp_path),
            tools=[FunctionTool.from_callable(_bash, name="bash")],
            auto_use_skills=False,
        )
        result = agent.run("use bash")
        assert ran == []  # settings.json denied it
        assert any(e.type == "tool_denied" for e in result.events)
