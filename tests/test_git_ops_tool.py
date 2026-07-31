"""Tests for GitOpsTool — structured git against a real temp repo."""

from __future__ import annotations

import subprocess

import pytest

from shipit_agent.tools import GitOpsTool
from shipit_agent.tools.base import ToolContext

CTX = ToolContext(prompt="", system_prompt="", state={})


@pytest.fixture()
def repo(tmp_path):
    def git(*argv):
        subprocess.run(["git", *argv], cwd=tmp_path, check=True,
                       capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t.com")
    git("config", "user.name", "Tester")
    (tmp_path / "a.txt").write_text("one\n")
    git("add", ".")
    git("commit", "-q", "-m", "initial")
    return tmp_path


class TestReadActions:
    def test_status_and_log(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        (repo / "a.txt").write_text("one\ntwo\n")
        status = tool.run(CTX, action="status")
        assert status.metadata["ok"] and "a.txt" in status.text
        log = tool.run(CTX, action="log", limit=5)
        assert "initial" in log.text

    def test_diff_and_show(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        (repo / "a.txt").write_text("one\ntwo\n")
        diff = tool.run(CTX, action="diff")
        assert "+two" in diff.text
        show = tool.run(CTX, action="show")
        assert "initial" in show.text

    def test_blame_requires_paths(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        assert tool.run(CTX, action="blame").metadata["ok"] is False
        blame = tool.run(CTX, action="blame", paths=["a.txt"])
        assert "Tester" in blame.text


class TestWriteActions:
    def test_add_commit_cycle(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        (repo / "b.txt").write_text("new file\n")
        tool.run(CTX, action="add", paths=["b.txt"])
        no_msg = tool.run(CTX, action="commit")
        assert no_msg.metadata["ok"] is False           # message required
        done = tool.run(CTX, action="commit", message="add b")
        assert done.metadata["ok"] is True
        assert "add b" in tool.run(CTX, action="log").text

    def test_stash_cycle(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        (repo / "a.txt").write_text("dirty\n")
        tool.run(CTX, action="stash", message="wip")
        assert "wip" in tool.run(CTX, action="stash_list").text
        tool.run(CTX, action="stash_pop")
        assert (repo / "a.txt").read_text() == "dirty\n"


class TestGatedActions:
    def test_push_and_reset_disabled_by_default(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo)
        for action in ("push", "reset"):
            out = tool.run(CTX, action=action)
            assert out.metadata["ok"] is False
            assert out.metadata["gated"] is True

    def test_reset_opt_in_works(self, repo) -> None:
        tool = GitOpsTool(root_dir=repo, allow_reset=True)
        (repo / "a.txt").write_text("dirty\n")
        out = tool.run(CTX, action="reset")
        assert out.metadata["ok"] is True
        assert (repo / "a.txt").read_text() == "one\n"

    def test_in_builtin_catalogue(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = [t.name for t in get_builtin_tools(project_root=".")]
        assert "git_ops" in names
