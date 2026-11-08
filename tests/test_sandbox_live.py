"""The sandbox for real: commands run under Seatbelt (macOS) or bubblewrap (Linux).

Skipped where neither is available. Each test checks what the sandbox must
refuse, so a sandbox that silently stopped working fails here.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

from shipit_agent.sandbox import SandboxPolicy, available_backend
from shipit_agent.sandbox.backends import writable_paths
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.bash import BashTool
from shipit_agent.tools.code_execution.code_execution_tool import CodeExecutionTool

pytestmark = pytest.mark.skipif(available_backend() is None, reason="no OS sandbox on this machine")

CONTEXT = ToolContext(prompt="")
NETWORK = "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\""


@pytest.fixture
def outside() -> Path:
    """A path outside the project and temp folders; removed if a broken sandbox writes it."""
    path = Path.home() / f".shipit_sandbox_probe_{uuid.uuid4().hex}"
    yield path
    path.unlink(missing_ok=True)


def bash(root: Path, **settings) -> BashTool:
    return BashTool(root_dir=root, sandbox_policy=SandboxPolicy.from_settings({"enabled": True, **settings}))


def run(tool: BashTool, command: str, **kwargs):
    out = tool.run(CONTEXT, command=command, **kwargs)
    return out.metadata["exit_code"], out.metadata["sandboxed"], out.text


def test_commands_write_in_the_project_but_nowhere_else(tmp_path: Path, outside: Path) -> None:
    tool = bash(tmp_path)
    assert run(tool, "echo hi > made.txt && cat made.txt")[:2] == (0, True)
    assert (tmp_path / "made.txt").read_text() == "hi\n"
    code, sandboxed, _ = run(tool, f"touch {outside}")
    assert (code, sandboxed) == (1, True) and not outside.exists()


def test_deny_write_and_added_folders(tmp_path: Path) -> None:
    root, shared, kept = tmp_path / "root", tmp_path / "shared", tmp_path / "root" / "kept"
    for folder in (root, shared, kept):
        folder.mkdir(parents=True, exist_ok=True)
    tool = bash(root, filesystem={"denyWrite": [str(kept)]})
    tool.extra_roots = (shared,)
    assert run(tool, f"echo x > {kept}/x.txt")[0] != 0 and not (kept / "x.txt").exists()
    assert run(tool, f"echo x > {shared}/x.txt")[0] == 0


def test_relative_paths_resolve_against_the_project_not_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, elsewhere = tmp_path / "project", tmp_path / "elsewhere"
    (root / "shared").mkdir(parents=True)
    elsewhere.mkdir()
    (root / ".env").write_text("KEY=1\n")
    (root / "secret.txt").write_text("hidden\n")
    monkeypatch.chdir(elsewhere)
    tool = bash(root, filesystem={"denyWrite": [".env"], "denyRead": ["secret.txt"]})
    assert run(tool, "echo changed >> .env")[0] != 0
    assert (root / ".env").read_text() == "KEY=1\n"
    code, _, text = run(tool, "cat secret.txt")
    assert code != 0 and "hidden" not in text
    assert run(tool, "echo ok > notes.txt")[0] == 0


def test_relative_allow_write_resolves_against_the_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cache, elsewhere = tmp_path / "project", tmp_path / "cache", tmp_path / "elsewhere"
    for folder in (root, cache, elsewhere):
        folder.mkdir()
    monkeypatch.chdir(elsewhere / "..")
    policy = SandboxPolicy.from_settings({"enabled": True, "filesystem": {"allowWrite": ["../cache"]}})
    writable = [os.path.realpath(p) for p in writable_paths([root], policy)]
    # The system temp folder is always writable, so check the resolved rule itself.
    assert os.path.realpath(cache) in writable
    assert os.path.realpath(tmp_path.parent / "cache") not in writable


def test_network_is_off_unless_allowed(tmp_path: Path) -> None:
    code, _, text = run(bash(tmp_path), NETWORK)
    assert code != 0 and ("not permitted" in text or "unreachable" in text.lower())


def test_excluded_and_approved_commands_run_outside(tmp_path: Path, outside: Path) -> None:
    tool = bash(tmp_path, excludedCommands=[f"touch {outside}"])
    assert run(tool, f"touch {outside}")[:2] == (0, False) and outside.exists()
    outside.unlink()
    assert run(bash(tmp_path), f"touch {outside}", dangerouslyDisableSandbox=True)[:2] == (0, False)
    outside.unlink()
    refused = bash(tmp_path, allowUnsandboxedCommands=False)
    assert run(refused, f"touch {outside}", dangerouslyDisableSandbox=True)[:2] == (1, True)
    assert not outside.exists()


def test_background_commands_are_sandboxed_too(tmp_path: Path, outside: Path) -> None:
    bash(tmp_path).run(CONTEXT, command=f"sleep 0.2; touch {outside}", background=True)
    time.sleep(1.0)
    assert not outside.exists()


def test_run_code_is_sandboxed(tmp_path: Path, outside: Path) -> None:
    tool = CodeExecutionTool(workspace_root=tmp_path, sandbox_policy=SandboxPolicy.from_settings({"enabled": True}))
    out = tool.run(CONTEXT, language="python", code=f"open({str(outside)!r}, 'w').write('x')")
    # Seatbelt says "Operation not permitted"; bubblewrap's read-only mounts say "Read-only file system".
    assert not outside.exists() and any(s in out.text.lower() for s in ("not permitted", "read-only file system"))
    ok = tool.run(CONTEXT, language="python", code="open('inside.txt', 'w').write('x'); print('done')")
    assert "done" in ok.text
