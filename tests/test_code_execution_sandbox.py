"""Tests for the Docker-sandbox path on CodeExecutionTool.

These tests never actually call `docker` — we validate the command
that WOULD be spawned, and verify the ENOENT fallback when docker is
missing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.tools.code_execution.sandbox import (
    SANDBOX_CMDS,
    SANDBOX_IMAGES,
    build_sandbox_command,
)


# ─────────────────────── sandbox helper (pure) ───────────────────────


class TestBuildSandboxCommand:
    def test_default_image_is_used(self, tmp_path: Path) -> None:
        script = tmp_path / "shipit.py"
        script.write_text("print('hi')")
        argv, cwd = build_sandbox_command(
            "python",
            script,
            tmp_path,
            allow_network=False,
            image=None,
        )
        assert argv[0] == "docker"
        assert "run" in argv and "--rm" in argv
        assert "--network" in argv
        assert argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv
        # Image comes from the default table.
        assert SANDBOX_IMAGES["python"] in argv
        # `python3 /work/shipit.py` at the tail.
        assert argv[-2:] == ["python3", "/work/shipit.py"]

    def test_network_flag_switches_to_bridge(self, tmp_path: Path) -> None:
        script = tmp_path / "a.py"
        script.write_text("1")
        argv, _ = build_sandbox_command(
            "python",
            script,
            tmp_path,
            allow_network=True,
            image=None,
        )
        i = argv.index("--network")
        assert argv[i + 1] == "bridge"

    def test_image_override_wins_over_default(self, tmp_path: Path) -> None:
        script = tmp_path / "a.py"
        script.write_text("1")
        argv, _ = build_sandbox_command(
            "python",
            script,
            tmp_path,
            allow_network=False,
            image="python:3.12-alpine",
        )
        assert "python:3.12-alpine" in argv
        # Default NOT present.
        assert SANDBOX_IMAGES["python"] not in argv

    def test_typescript_installs_tsx_inside(self, tmp_path: Path) -> None:
        script = tmp_path / "a.ts"
        script.write_text("const x=1")
        argv, _ = build_sandbox_command(
            "typescript",
            script,
            tmp_path,
            allow_network=False,
            image=None,
        )
        # The inside-container command should invoke `tsx` via sh -c.
        joined = " ".join(argv)
        assert "tsx" in joined and "npm install -g" in joined

    def test_unknown_language_raises(self, tmp_path: Path) -> None:
        script = tmp_path / "a.xyz"
        script.write_text("x")
        with pytest.raises(RuntimeError, match="No sandbox image"):
            build_sandbox_command(
                "cobol",
                script,
                tmp_path,
                allow_network=False,
                image=None,
            )

    def test_mount_path_is_read_only_workspace_slash_work(self, tmp_path: Path) -> None:
        script = tmp_path / "a.py"
        script.write_text("1")
        argv, _ = build_sandbox_command(
            "python",
            script,
            tmp_path,
            allow_network=False,
            image=None,
        )
        mount_arg = argv[argv.index("-v") + 1]
        assert mount_arg == f"{tmp_path.resolve()}:/work:ro"
        assert argv[argv.index("-w") + 1] == "/work"

    def test_every_registered_image_has_a_cmd(self) -> None:
        # Sanity: every language with an image also has an inside-cmd.
        for lang in SANDBOX_IMAGES:
            assert lang in SANDBOX_CMDS, f"missing SANDBOX_CMDS for {lang!r}"


# ─────────────────────── tool-level integration ───────────────────────


class TestCodeExecutionSandboxIntegration:
    def test_sandbox_schema_exposes_flag(self, tmp_path: Path) -> None:
        tool = CodeExecutionTool(workspace_root=tmp_path)
        props = tool.schema()["function"]["parameters"]["properties"]
        assert "sandbox" in props and props["sandbox"]["default"] is False
        assert "network" in props and props["network"]["default"] is False
        assert "image" in props

    def test_sandbox_false_takes_local_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # When sandbox=False, the tool does NOT call the sandbox builder —
        # it goes through `_command_for_language` like before. Easiest way
        # to verify: patch subprocess.run to capture argv and ensure
        # "docker" isn't there.
        captured: dict[str, Any] = {}

        def _fake_run(argv, **kw):
            captured["argv"] = argv

            class _C:
                returncode = 0
                stdout = "ok\n"
                stderr = ""

            return _C()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tool = CodeExecutionTool(workspace_root=tmp_path)
        out = tool.run(
            ToolContext(prompt="demo"),
            language="python",
            code="print('hi')",
        )
        # The pre-existing code_execution tool doesn't set an "ok" key in
        # metadata — it returns exit_code instead. Verify docker was NOT
        # invoked and the sandbox flag is false.
        assert out.metadata["exit_code"] == 0
        assert "docker" not in captured["argv"][0]
        assert out.metadata.get("sandbox") is False

    def test_sandbox_true_calls_docker_argv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(argv, **kw):
            captured["argv"] = argv

            class _C:
                returncode = 0
                stdout = "sandboxed\n"
                stderr = ""

            return _C()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tool = CodeExecutionTool(workspace_root=tmp_path)
        out = tool.run(
            ToolContext(prompt="demo"),
            language="python",
            code="print('sandboxed')",
            sandbox=True,
        )
        assert out.metadata["sandbox"] is True
        assert out.metadata["sandbox_network"] is False
        assert out.metadata["sandbox_image"] == SANDBOX_IMAGES["python"]
        argv = captured["argv"]
        assert argv[0] == "docker"
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv

    def test_sandbox_docker_missing_returns_clean_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise(argv, **kw):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(subprocess, "run", _raise)
        tool = CodeExecutionTool(workspace_root=tmp_path)
        out = tool.run(
            ToolContext(prompt="demo"),
            language="python",
            code="print('hi')",
            sandbox=True,
        )
        assert out.metadata["ok"] is False
        assert "docker is not installed" in out.text

    def test_network_flag_passed_through(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(argv, **kw):
            captured["argv"] = argv

            class _C:
                returncode = 0
                stdout = ""
                stderr = ""

            return _C()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tool = CodeExecutionTool(workspace_root=tmp_path)
        tool.run(
            ToolContext(prompt="demo"),
            language="python",
            code="print('net')",
            sandbox=True,
            network=True,
        )
        argv = captured["argv"]
        assert argv[argv.index("--network") + 1] == "bridge"
