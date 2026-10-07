"""Model-controlled subprocess tools must not leak the host environment.

``bash`` and ``run_code`` run commands the model wrote. Anything in the host
process environment (API keys loaded by dotenv, DB passwords, SECRET_KEY) was
readable with ``printenv`` / ``os.environ``. These tests pin the scrubbed
default and the explicit opt-ins.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.bash.bash_tool import BashJobTool, BashTool
from shipit_agent.tools.code_execution import CodeExecutionTool
from shipit_agent.tools.subprocess_env import SAFE_ENV_NAMES, build_tool_env

SECRET_NAME = "SHIPIT_TEST_SECRET_7F3A"
SECRET_VALUE = "s3cr3t-value-that-must-not-leak"


@pytest.fixture()
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)


def _ctx() -> ToolContext:
    return ToolContext(prompt="env test")


class TestBuildToolEnv:
    def test_drops_unlisted_vars(self) -> None:
        env = build_tool_env(parent={"PATH": "/bin", SECRET_NAME: SECRET_VALUE})
        assert env["PATH"] == "/bin"
        assert SECRET_NAME not in env

    def test_keeps_safe_basics_and_locale_prefix(self) -> None:
        parent = {
            "HOME": "/home/u",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "LC_CTYPE": "UTF-8",
            "TERM": "xterm",
            "TMPDIR": "/tmp/x",
            "PATH": "/usr/bin",
        }
        env = build_tool_env(parent=parent)
        for name, value in parent.items():
            assert env[name] == value

    def test_path_falls_back_to_default_when_missing(self) -> None:
        env = build_tool_env(parent={})
        assert env["PATH"] == os.defpath
        assert env["PYTHONIOENCODING"] == "utf-8"

    def test_does_not_keep_ssh_agent_socket(self) -> None:
        env = build_tool_env(parent={"SSH_AUTH_SOCK": "/tmp/agent.sock"})
        assert "SSH_AUTH_SOCK" not in env
        assert "SSH_AUTH_SOCK" not in SAFE_ENV_NAMES

    def test_allowlist_passes_named_vars_only(self) -> None:
        parent = {SECRET_NAME: SECRET_VALUE, "OTHER": "x"}
        env = build_tool_env(parent=parent, allowlist=[SECRET_NAME, "MISSING"])
        assert env[SECRET_NAME] == SECRET_VALUE
        assert "OTHER" not in env
        assert "MISSING" not in env

    def test_extra_env_overrides_everything(self) -> None:
        env = build_tool_env(
            parent={"HOME": "/home/u"},
            extra_env={"HOME": "/workspace", "FEATURE": "on"},
        )
        assert env["HOME"] == "/workspace"
        assert env["FEATURE"] == "on"

    def test_inherit_passes_whole_parent(self) -> None:
        env = build_tool_env(parent={SECRET_NAME: SECRET_VALUE}, inherit=True)
        assert env[SECRET_NAME] == SECRET_VALUE

    def test_empty_inputs(self) -> None:
        env = build_tool_env(parent={}, allowlist=[], extra_env={})
        assert set(env) == {"PATH", "PYTHONIOENCODING"}

    def test_defaults_to_os_environ(self, secret_env: None) -> None:
        env = build_tool_env()
        assert SECRET_NAME not in env
        assert env["PATH"] == os.environ["PATH"]


class TestBashToolEnv:
    def test_secret_not_visible_to_printenv(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        out = BashTool(root_dir=tmp_path).run(_ctx(), command=f"printenv {SECRET_NAME}")
        assert SECRET_VALUE not in out.text
        assert out.metadata["exit_code"] != 0

    def test_secret_not_in_env_dump(self, tmp_path: Path, secret_env: None) -> None:
        out = BashTool(root_dir=tmp_path).run(_ctx(), command="env")
        assert out.metadata["exit_code"] == 0
        assert SECRET_VALUE not in out.metadata["stdout"]
        assert SECRET_NAME not in out.metadata["stdout"]

    def test_path_still_resolves_commands(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        (tmp_path / "marker.txt").write_text("x")
        out = BashTool(root_dir=tmp_path).run(_ctx(), command="ls")
        assert out.metadata["exit_code"] == 0
        assert "marker.txt" in out.metadata["stdout"]

    def test_allowlisted_var_passes_through(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        tool = BashTool(root_dir=tmp_path, env_allowlist=[SECRET_NAME])
        out = tool.run(_ctx(), command=f"printenv {SECRET_NAME}")
        assert out.metadata["stdout"].strip() == SECRET_VALUE

    def test_extra_env_sets_value(self, tmp_path: Path) -> None:
        tool = BashTool(root_dir=tmp_path, extra_env={"SHIPIT_FLAG": "on"})
        out = tool.run(_ctx(), command="printenv SHIPIT_FLAG")
        assert out.metadata["stdout"].strip() == "on"

    def test_inherit_env_opt_in(self, tmp_path: Path, secret_env: None) -> None:
        tool = BashTool(root_dir=tmp_path, inherit_env=True)
        out = tool.run(_ctx(), command=f"printenv {SECRET_NAME}")
        assert out.metadata["stdout"].strip() == SECRET_VALUE

    def test_background_job_does_not_see_secret(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        bash = BashTool(root_dir=tmp_path)
        started = bash.run(_ctx(), command="env", background=True)
        job_id = started.metadata["job_id"]
        job = BashJobTool(bash)
        deadline = time.monotonic() + 10
        result = job.run(_ctx(), job_id=job_id, tail_lines=500)
        while result.metadata["running"] and time.monotonic() < deadline:
            time.sleep(0.1)
            result = job.run(_ctx(), job_id=job_id, tail_lines=500)
        assert result.metadata["exit_code"] == 0
        assert "PATH=" in result.metadata["output"]
        assert SECRET_VALUE not in result.metadata["output"]

    def test_background_job_allowlist(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        bash = BashTool(root_dir=tmp_path, env_allowlist=[SECRET_NAME])
        started = bash.run(_ctx(), command=f"printenv {SECRET_NAME}", background=True)
        assert SECRET_VALUE in started.metadata["early_output"]


class TestCodeExecutionEnv:
    def _run_python(self, tool: CodeExecutionTool) -> Any:
        return tool.run(
            _ctx(),
            language="python",
            code=f"import os; print(os.environ.get({SECRET_NAME!r}))",
        )

    def test_secret_not_visible(self, tmp_path: Path, secret_env: None) -> None:
        out = self._run_python(CodeExecutionTool(workspace_root=tmp_path))
        assert out.metadata["exit_code"] == 0
        assert out.metadata["stdout"].strip() == "None"

    def test_bash_language_cannot_printenv_secret(
        self, tmp_path: Path, secret_env: None
    ) -> None:
        out = CodeExecutionTool(workspace_root=tmp_path).run(
            _ctx(), language="bash", code=f"printenv {SECRET_NAME} || echo absent"
        )
        assert out.metadata["stdout"].strip() == "absent"

    def test_allowlist_opt_in(self, tmp_path: Path, secret_env: None) -> None:
        tool = CodeExecutionTool(workspace_root=tmp_path, env_allowlist=[SECRET_NAME])
        assert self._run_python(tool).metadata["stdout"].strip() == SECRET_VALUE

    def test_inherit_env_opt_in(self, tmp_path: Path, secret_env: None) -> None:
        tool = CodeExecutionTool(workspace_root=tmp_path, inherit_env=True)
        assert self._run_python(tool).metadata["stdout"].strip() == SECRET_VALUE

    def test_extra_env_sets_value(self, tmp_path: Path) -> None:
        tool = CodeExecutionTool(workspace_root=tmp_path, extra_env={"SHIPIT_FLAG": "on"})
        out = tool.run(
            _ctx(),
            language="python",
            code="import os; print(os.environ['SHIPIT_FLAG'])",
        )
        assert out.metadata["stdout"].strip() == "on"

    def test_sandbox_docker_cli_keeps_docker_vars_not_secrets(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        secret_env: None,
    ) -> None:
        monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/colima.sock")
        monkeypatch.setenv("DOCKER_CONTEXT", "colima")
        captured: dict[str, Any] = {}

        def _fake_run(argv: list[str], **kw: Any) -> Any:
            captured.update(kw)
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        CodeExecutionTool(workspace_root=tmp_path).run(
            _ctx(), language="python", code="print(1)", sandbox=True
        )
        env = captured["env"]
        assert env["DOCKER_HOST"] == "unix:///tmp/colima.sock"
        assert env["DOCKER_CONTEXT"] == "colima"
        assert SECRET_NAME not in env

    def test_local_path_does_not_pass_docker_vars(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/colima.sock")
        captured: dict[str, Any] = {}

        def _fake_run(argv: list[str], **kw: Any) -> Any:
            captured.update(kw)
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        CodeExecutionTool(workspace_root=tmp_path).run(
            _ctx(), language="python", code="print(1)"
        )
        assert "DOCKER_HOST" not in captured["env"]


def test_python_interpreter_runs_under_scrubbed_env() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        env=build_tool_env(parent={}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout.strip() == "ok"
