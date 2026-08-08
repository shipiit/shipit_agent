"""Tests for human-in-the-loop prompts and the bottom-input TUI."""

from __future__ import annotations

import io

from shipit_agent import console_permission_prompt
from shipit_agent.cli.tui import BottomInputTerminal


class TestConsolePermissionPrompt:
    def _prompt(self, answers, always=None):
        it = iter(answers)
        writes: list[str] = []
        cb = console_permission_prompt(
            always_allowed=always, input_fn=lambda: next(it), output=writes.append
        )
        return cb, writes

    def test_yes_no_always(self) -> None:
        always: set[str] = set()
        cb, writes = self._prompt(["1", "3", "2"], always)  # menu numbers
        assert cb("bash", {"command": "ls"}).allowed
        assert not cb("bash", {"command": "rm x"}).allowed
        assert cb("bash", {"command": "pwd"}).allowed
        # always persisted — no more input consumed
        assert cb("bash", {"command": "anything"}).allowed
        assert "bash" in always
        joined = "".join(writes)
        assert "requires approval" in joined
        assert "don't ask again for:" in joined
        assert "1. Yes" in joined and "3. No" in joined

    def test_eof_denies(self) -> None:
        def boom():
            raise EOFError

        cb = console_permission_prompt(input_fn=boom, output=lambda _t: None)
        assert not cb("bash", {}).allowed

    def test_shared_always_set_across_callbacks(self) -> None:
        shared: set[str] = {"git_ops"}
        cb = console_permission_prompt(
            always_allowed=shared, input_fn=lambda: "n", output=lambda _t: None
        )
        assert cb("git_ops", {"action": "status"}).allowed  # pre-approved


class TestBottomInputTerminal:
    def test_non_tty_is_plain_passthrough(self, capsys) -> None:
        buf = io.StringIO()  # not a tty
        term = BottomInputTerminal(stream=buf).start()
        assert term.enabled is False
        term.print("hello")
        term.stop()
        assert buf.getvalue() == "hello\n"
        assert "\033[" not in buf.getvalue()

    def test_enabled_uses_scroll_region(self, monkeypatch) -> None:
        import shutil as _shutil

        monkeypatch.setattr(
            _shutil,
            "get_terminal_size",
            lambda fallback=None: type("S", (), {"lines": 24, "columns": 80})(),
        )
        buf = io.StringIO()
        term = BottomInputTerminal(stream=buf, enabled=True).start()
        assert term.enabled
        term.print("chat line")
        term.stop()
        out = buf.getvalue()
        assert "\033[1;22r" in out  # scroll region rows 1..height-2
        assert "chat line" in out
        assert "\033[r" in out  # region reset on stop

    def test_read_falls_back_to_input(self, monkeypatch) -> None:
        import builtins

        monkeypatch.setattr(builtins, "input", lambda p="": "typed")
        term = BottomInputTerminal(stream=io.StringIO())  # disabled
        assert term.read("you ▸ ") == "typed"

    def test_tiny_terminal_disables_layout(self, monkeypatch) -> None:
        import shutil as _shutil

        monkeypatch.setattr(
            _shutil,
            "get_terminal_size",
            lambda fallback=None: type("S", (), {"lines": 4, "columns": 80})(),
        )
        term = BottomInputTerminal(stream=io.StringIO(), enabled=True).start()
        assert term.enabled is False


class TestBrowseCommand:
    def test_browse_parser_registered(self) -> None:
        from shipit_agent.cli import build_parser

        args = build_parser().parse_args(
            ["browse", "find flights", "--show", "--max-steps", "8"]
        )
        assert args.goal == "find flights"
        assert args.show is True and args.max_steps == 8
        assert args.storage_state.endswith("browser_state.json")

    def test_browse_in_help(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main([]) == 0
        assert "browse" in capsys.readouterr().out


class TestMcpFlag:
    def test_playwright_in_catalog(self) -> None:
        from shipit_agent import MCP_CATALOG

        entry = MCP_CATALOG["playwright"]
        assert "@playwright/mcp" in " ".join(entry.command)
        assert entry.required_env == []

    def test_mcp_flag_parsed_everywhere(self) -> None:
        from shipit_agent.cli import build_parser

        p = build_parser()
        assert p.parse_args(["run", "x", "--mcp", "playwright"]).mcp == "playwright"
        assert (
            p.parse_args(["code", "x", "--mcp", "playwright,filesystem"]).mcp
            == "playwright,filesystem"
        )
        assert p.parse_args(["serve", "--mcp", "github"]).mcp == "github"

    def test_build_agent_attaches_servers(self, monkeypatch) -> None:
        import shipit_agent
        from shipit_agent.cli.llm import build_agent

        connected: list[str] = []
        monkeypatch.setattr(
            shipit_agent,
            "connect_mcp",
            lambda name, **_kw: (
                connected.append(name)
                or type(
                    "S",
                    (),
                    {"name": name, "tools": [], "discover_tools": lambda self: []},
                )()
            ),
        )
        args = type(
            "A",
            (),
            {
                "provider": "echo",
                "model": None,
                "role": None,
                "guardrails": None,
                "project_root": None,
                "mcp": "playwright,filesystem",
            },
        )()
        agent = build_agent(args)
        assert connected == ["playwright", "filesystem"]
        assert len(agent.mcps) == 2


class TestBareShipitOpensChat:
    def test_tty_routes_to_chat(self, monkeypatch) -> None:
        import shipit_agent.cli as cli

        monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
        called = {}
        import shipit_agent.chat_cli as chat_cli

        monkeypatch.setattr(
            chat_cli, "main", lambda argv: called.setdefault("argv", argv) or 0
        )
        assert cli.main([]) == 0
        assert called["argv"] == []

    def test_non_tty_keeps_help(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main([]) == 0  # captured stdout ≠ tty
        assert "serve" in capsys.readouterr().out


class TestJobsCommand:
    def test_add_list_remove_roundtrip(self, tmp_path, capsys) -> None:
        from shipit_agent.cli import main

        db = str(tmp_path / "jobs.db")
        assert (
            main(
                [
                    "jobs",
                    "add",
                    "hourly digest",
                    "--every",
                    "3600",
                    "--name",
                    "digest",
                    "--db",
                    db,
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "jobs",
                    "add",
                    "daily post",
                    "--at",
                    "09:00",
                    "--name",
                    "post",
                    "--db",
                    db,
                ]
            )
            == 0
        )
        assert main(["jobs", "list", "--db", db]) == 0
        out = capsys.readouterr().out
        assert "digest" in out and "daily 09:00" in out and "every 3600s" in out
        assert main(["jobs", "remove", "digest", "--db", db]) == 0
        capsys.readouterr()  # consume the "✓ removed" line
        assert main(["jobs", "list", "--db", db]) == 0
        assert "digest" not in capsys.readouterr().out

    def test_add_requires_a_schedule(self, tmp_path) -> None:
        from shipit_agent.cli import main

        assert main(["jobs", "add", "x", "--db", str(tmp_path / "j.db")]) == 1

    def test_remove_unknown_job(self, tmp_path) -> None:
        from shipit_agent.cli import main

        assert main(["jobs", "remove", "ghost", "--db", str(tmp_path / "j.db")]) == 1

    def test_job_persists_runtime_capabilities_and_pause_state(
        self, tmp_path, capsys
    ) -> None:
        from shipit_agent import SQLiteJobStore
        from shipit_agent.cli import main

        db = str(tmp_path / "jobs.db")
        args = [
            "jobs",
            "add",
            "audit release",
            "--every",
            "60",
            "--name",
            "audit",
            "--provider",
            "openai",
            "--model",
            "gpt-test",
            "--runtime",
            "project",
            "--guardrails",
            "off",
            "--mcp",
            "github,sentry",
            "--connection",
            "slack",
            "--skill",
            "release-audit,testing",
            "--no-auto-skills",
            "--session-id",
            "release-session",
            "--stream-events",
            "--db",
            db,
        ]
        assert main(args) == 0
        store = SQLiteJobStore(db)
        job = store.load("audit")
        assert job is not None
        assert job.agent_config.guardrails is None
        assert job.agent_config.mcps == ["github", "sentry"]
        assert job.agent_config.connections == ["slack"]
        assert job.agent_config.skills == ["release-audit", "testing"]
        assert job.agent_config.auto_use_skills is False
        assert job.agent_config.stream_events is True
        store.close()

        assert main(["jobs", "pause", "audit", "--db", db]) == 0
        assert main(["jobs", "list", "--db", db]) == 0
        output = capsys.readouterr().out
        assert "paused" in output
        assert "skills=release-audit,testing" in output
        assert main(["jobs", "resume", "audit", "--db", db]) == 0


class TestConsoleAskUser:
    def test_prompts_and_returns_answer(self) -> None:
        from shipit_agent.hitl import ConsoleAskUserTool

        writes: list[str] = []
        tool = ConsoleAskUserTool(input_fn=lambda: "2", output=writes.append)
        out = tool.run(None, question="Which env?", options=["staging", "production"])
        assert out.text == "production"  # numeric pick → option text
        joined = "".join(writes)
        assert "❓ Which env?" in joined and "1. staging" in joined

    def test_eof_gives_safe_default(self) -> None:
        from shipit_agent.hitl import ConsoleAskUserTool

        def boom():
            raise EOFError

        out = ConsoleAskUserTool(input_fn=boom, output=lambda _t: None).run(
            None, question="?"
        )
        assert "best judgment" in out.text

    def test_cli_agent_gets_console_variant(self) -> None:
        from types import SimpleNamespace as ns

        from shipit_agent.cli.llm import build_agent
        from shipit_agent.hitl import ConsoleAskUserTool

        agent = build_agent(
            ns(
                provider="echo",
                model=None,
                role=None,
                guardrails=None,
                project_root=".",
                mcp=None,
            )
        )
        ask = [t for t in agent.tools if t.name == "ask_user"]
        assert len(ask) == 1 and isinstance(ask[0], ConsoleAskUserTool)


class TestApprovalCardUI:
    def test_full_multiline_command_shown(self) -> None:
        from shipit_agent import console_permission_prompt

        writes: list[str] = []
        cb = console_permission_prompt(input_fn=lambda: "1", output=writes.append)
        long_cmd = "cd /src\npytest tests/ -q 2>&1 | tail -15\necho done"
        assert cb("bash", {"command": long_cmd}).allowed
        joined = "".join(writes)
        assert "pytest tests/ -q" in joined  # full body, not truncated
        assert "echo done" in joined
        assert "Bash" in joined  # title-cased header

    def test_letter_answers_still_work(self) -> None:
        from shipit_agent import console_permission_prompt

        answers = iter(["yes", "no"])
        cb = console_permission_prompt(
            input_fn=lambda: next(answers), output=lambda _t: None
        )
        assert cb("bash", {"command": "ls"}).allowed
        assert not cb("bash", {"command": "rm"}).allowed
