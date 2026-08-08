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
from shipit_agent.stores import FileMemoryStore, FileSessionStore


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
        assert (
            load_settings(tmp_path, include_user=False).to_permission_engine() is None
        )

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
            return LLMResponse(
                content="", tool_calls=[ToolCall(name=self._tool, arguments={})]
            )
        return LLMResponse(content="done")


class _EditFlowLLM:
    model = "gpt-4o"

    def __init__(self) -> None:
        self._turn = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        steps = [
            ToolCall(
                name="write_file",
                arguments={"path": "live.txt", "content": "alpha\n"},
            ),
            ToolCall(name="read_file", arguments={"path": "live.txt"}),
            ToolCall(
                name="edit_file",
                arguments={
                    "path": "live.txt",
                    "old_text": "alpha",
                    "new_text": "beta",
                },
            ),
        ]
        if self._turn < len(steps):
            call = steps[self._turn]
            self._turn += 1
            return LLMResponse(content="", tool_calls=[call])
        return LLMResponse(content="Created, read, and patched live.txt.")


class TestAgentIntegration:
    def test_project_memory_in_prompt(self, tmp_path) -> None:
        (tmp_path / "SHIPIT.md").write_text("Always answer in haiku.", encoding="utf-8")
        agent = Agent(
            llm=ShipitLLM(), project_root=str(tmp_path), auto_use_skills=False
        )
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
        agent = Agent(
            llm=ShipitLLM(), project_root=str(tmp_path), auto_use_skills=False
        )
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

    def test_optimized_project_agent_resumes_durable_chat_after_restart(
        self, tmp_path
    ) -> None:
        first = Agent.for_project(
            llm=ShipitLLM(),
            project_root=tmp_path,
            optimized=True,
            auto_use_skills=False,
        )
        first.chat_session(session_id="main").send("remember alpha")

        restarted = Agent.for_project(
            llm=ShipitLLM(),
            project_root=tmp_path,
            optimized=True,
            auto_use_skills=False,
        )
        chat = restarted.chat_session(session_id="main")
        assert any(message.content == "remember alpha" for message in chat.history())

        chat.send("now beta")
        user_messages = [
            message.content for message in chat.history() if message.role == "user"
        ]

        assert user_messages == ["remember alpha", "now beta"]
        assert isinstance(restarted.session_store, FileSessionStore)
        assert isinstance(restarted.memory_store, FileMemoryStore)
        assert (tmp_path / ".shipit" / "sessions" / "main.json").is_file()
        assert (tmp_path / ".shipit" / "memory.json").is_file()

    def test_optimized_project_agent_preserves_explicit_stores(self, tmp_path) -> None:
        from shipit_agent.stores import InMemoryMemoryStore, InMemorySessionStore

        sessions = InMemorySessionStore()
        memory = InMemoryMemoryStore()
        agent = Agent.for_project(
            llm=ShipitLLM(),
            project_root=tmp_path,
            optimized=True,
            session_store=sessions,
            memory_store=memory,
            auto_use_skills=False,
        )

        assert agent.session_store is sessions
        assert agent.memory_store is memory
        assert not (tmp_path / ".shipit" / "sessions").exists()
        assert not (tmp_path / ".shipit" / "memory.json").exists()

    def test_optimized_project_agent_runs_a_real_multi_step_edit_flow(
        self, tmp_path
    ) -> None:
        agent = Agent.for_project(
            llm=_EditFlowLLM(),
            project_root=tmp_path,
            optimized=True,
            auto_use_skills=False,
        )

        result = agent.chat_session(session_id="edit-flow").send(
            "Create live.txt, inspect it, and change alpha to beta."
        )

        assert (tmp_path / "live.txt").read_text(encoding="utf-8") == "beta\n"
        assert [item.name for item in result.tool_results][-3:] == [
            "write_file",
            "read_file",
            "edit_file",
        ]
        assert any(event.type == "planning_completed" for event in result.events)
        assert result.output == "Created, read, and patched live.txt."
        assert agent.code_mode is True
        assert agent.context_window_tokens == 128_000
