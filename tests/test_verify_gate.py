"""VerifyGate — the runtime's edit/verify tracking and the stop decision. Driven
directly (no agent loop) so every branch of the policy is pinned."""

from __future__ import annotations

import pytest

from shipit_agent.verify import VerifyGate


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()          # → detect_verify_commands finds "pytest"
    return tmp_path


def _gate(project):
    return VerifyGate(session_id="s", root=project, db_path=":memory:")


def test_detects_the_project_verify_commands(project):
    assert "pytest" in _gate(project).commands


def test_no_edit_no_nudge(project):
    gate = _gate(project)
    gate.note_tool(read_only=True, paths=["app.py"])   # a read, not an edit
    assert gate.stop_nudge() is None


def test_edit_without_verification_nudges(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"])  # edited code
    nudge = gate.stop_nudge()
    assert nudge and "pytest" in nudge and "done" in nudge.lower()


def test_docs_only_edit_never_nudges(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["README.md", "LICENSE"])
    assert gate.edited_this_turn is False
    assert gate.stop_nudge() is None


def test_edit_then_passing_run_lets_it_stop(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"])
    gate.note_tool(read_only=False, command="pytest -q", exit_code=0, output="1 passed")
    assert gate.stop_nudge() is None                    # fresh passing evidence


def test_edit_then_failing_run_still_nudges(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"])
    gate.note_tool(read_only=False, command="pytest -q", exit_code=1, output="1 failed: test_x")
    nudge = gate.stop_nudge()
    assert nudge and "1 failed: test_x" in nudge


def test_edit_after_a_pass_dirties_again(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"])
    gate.note_tool(read_only=False, command="pytest", exit_code=0)
    assert gate.stop_nudge() is None
    gate.note_tool(read_only=False, paths=["app.py"])   # edited again
    assert gate.stop_nudge() is not None                # stale again


def test_nudge_is_bounded(project):
    gate = VerifyGate(session_id="s", root=project, db_path=":memory:", max_attempts=2)
    gate.note_tool(read_only=False, paths=["app.py"])
    assert gate.stop_nudge() is not None                # attempt 1
    assert gate.stop_nudge() is not None                # attempt 2
    assert gate.stop_nudge() is None                    # capped — lets it stop


def test_non_verify_command_is_not_recorded(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"])
    gate.note_tool(read_only=False, command="git status", exit_code=0)  # not a verify cmd
    assert gate.stop_nudge() is not None                # still unverified


def test_no_verify_commands_makes_it_a_noop(tmp_path):
    # An empty (non-code) project has no verify commands → the gate never fires.
    gate = VerifyGate(session_id="s", root=tmp_path, db_path=":memory:")
    assert gate.commands == []
    gate.note_tool(read_only=False, paths=["app.py"])
    assert gate.stop_nudge() is None


def test_project_root_from_output_dir():
    assert VerifyGate.project_root_from_output_dir(
        "/proj/.shipit/tool-results") == "/proj"
    assert VerifyGate.project_root_from_output_dir("") == "."


def test_failed_edit_is_not_counted(project):
    gate = _gate(project)
    gate.note_tool(read_only=False, paths=["app.py"], ok=False)  # edit failed
    assert gate.edited_this_turn is False
    assert gate.stop_nudge() is None


def test_would_nudge_does_not_consume_an_attempt(project):
    gate = VerifyGate(session_id="s", root=project, db_path=":memory:", max_attempts=1)
    gate.note_tool(read_only=False, paths=["app.py"])
    assert gate.would_nudge() is True
    assert gate.would_nudge() is True          # non-consuming — still true
    assert gate.stop_nudge() is not None       # attempt 1
    assert gate.stop_nudge() is None           # capped
    assert gate.would_nudge() is True          # ...but the condition still holds
