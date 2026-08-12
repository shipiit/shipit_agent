"""Tool-depth upgrades: bash unrestricted + 600s + background poll/kill,
multi_edit atomic batch, git worktree, and readability web extraction.
"""

from __future__ import annotations

from shipit_agent.tools.bash import BashJobTool, BashTool
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file import MultiEditTool
from shipit_agent.tools.file_read import FileReadTool
from shipit_agent.tools.git_ops import GitOpsTool
from shipit_agent.tools.open_url.open_url_tool import _strip_html


def _ctx(state=None):
    return ToolContext(prompt="", state=state if state is not None else {})


# ── bash ─────────────────────────────────────────────────────────────────


def test_bash_default_rejects_redirection_gracefully():
    tool = BashTool(root_dir="/tmp")
    out = tool.run(_ctx(), command="echo hi > out.txt")
    assert out.metadata.get("error") == "invalid_command"
    assert "redirection" in out.text.lower()


def test_bash_unrestricted_allows_redirection_and_substitution(tmp_path):
    tool = BashTool(root_dir=str(tmp_path), unrestricted=True)
    out = tool.run(_ctx(), command=f"echo hi > {tmp_path}/out.txt && cat {tmp_path}/out.txt")
    assert out.metadata.get("exit_code") == 0
    assert "hi" in out.text


def test_bash_timeout_ceiling_is_600s():
    assert BashTool(root_dir="/tmp").max_timeout == 600.0


def test_bash_background_job_poll_and_kill(tmp_path):
    tool = BashTool(root_dir=str(tmp_path), unrestricted=True)
    job = BashJobTool(tool)
    out = tool.run(_ctx(), command="sleep 30", background=True)
    job_id = out.metadata["job_id"]
    # Poll: it's running.
    status = job.run(_ctx(), job_id=job_id, action="output")
    assert status.metadata["running"] is True
    # Kill it.
    killed = job.run(_ctx(), job_id=job_id, action="kill")
    assert killed.metadata.get("killed") is True


# ── multi_edit ───────────────────────────────────────────────────────────


def _read_gate(tmp_path, path):
    state = {}
    FileReadTool(root_dir=str(tmp_path)).run(_ctx(state), path=path)
    return state


def test_multi_edit_applies_batch_atomically(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("alpha\nbeta\ngamma\n")
    state = _read_gate(tmp_path, "code.py")
    out = MultiEditTool(root_dir=str(tmp_path)).run(
        _ctx(state), path="code.py",
        edits=[
            {"old_text": "alpha", "new_text": "ALPHA"},
            {"old_text": "gamma", "new_text": "GAMMA"},
        ],
    )
    assert out.metadata["edits_applied"] == 2
    assert f.read_text() == "ALPHA\nbeta\nGAMMA\n"


def test_multi_edit_is_all_or_nothing(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("alpha\nbeta\n")
    state = _read_gate(tmp_path, "code.py")
    out = MultiEditTool(root_dir=str(tmp_path)).run(
        _ctx(state), path="code.py",
        edits=[
            {"old_text": "alpha", "new_text": "ALPHA"},
            {"old_text": "nonexistent", "new_text": "X"},  # fails
        ],
    )
    assert "failed at edit #2" in out.text
    assert f.read_text() == "alpha\nbeta\n"  # nothing written


def test_multi_edit_requires_a_prior_read(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("alpha\n")
    out = MultiEditTool(root_dir=str(tmp_path)).run(
        _ctx({}), path="code.py", edits=[{"old_text": "alpha", "new_text": "X"}]
    )
    assert "read the file first" in out.text


# ── git worktree ─────────────────────────────────────────────────────────


def test_git_ops_exposes_worktree_actions():
    tool = GitOpsTool(root_dir="/tmp")
    assert "worktree_add" in tool.ACTIONS
    assert "worktree_remove" in tool.ACTIONS
    assert "worktree_list" in tool.ACTIONS


def test_worktree_add_needs_a_path():
    out = GitOpsTool(root_dir="/tmp").run(_ctx(), action="worktree_add")
    assert "needs `ref`" in out.text


# ── readability web extraction ───────────────────────────────────────────


def test_strip_html_produces_structured_markdown():
    html = (
        "<html><head><script>evil()</script></head><body>"
        "<nav>Home About</nav>"
        "<h1>Main Title</h1><p>A paragraph.</p>"
        "<ul><li>one</li><li>two</li></ul>"
        "<footer>copyright</footer></body></html>"
    )
    md = _strip_html(html)
    assert "# Main Title" in md
    assert "- one" in md and "- two" in md
    assert "evil" not in md  # script dropped
    assert "copyright" not in md  # footer chrome dropped
    assert "Home About" not in md  # nav dropped
