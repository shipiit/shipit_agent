"""The verification ledger — the edit-dirty / pass-clean state machine, project
verify-command detection, and the gate helpers (path filter, command classify,
nudge). All standalone; the loop wiring is a separate PR."""

from __future__ import annotations

import pytest

from shipit_agent.verify import (
    VerificationLedger,
    build_verify_nudge,
    classify_command,
    detect_verify_commands,
    is_verifiable_path,
)


class _Clock:
    """A hand-cranked clock so 'edit then verify' ordering is deterministic."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, by: float = 1.0) -> float:
        self.t += by
        return self.t


@pytest.fixture
def ledger():
    lg = VerificationLedger(":memory:", clock=_Clock())
    yield lg
    lg.close()


# ── ledger state machine ──────────────────────────────────────────────────────


def test_untouched_workspace_is_not_applicable(ledger):
    assert ledger.status(session_id="s", root="/proj").status == "not_applicable"


def test_edit_makes_it_unverified(ledger):
    ledger.mark_edited(session_id="s", root="/proj", paths=["app.py"])
    assert ledger.status(session_id="s", root="/proj").status == "unverified"


def test_passing_run_after_edit_is_passed(ledger):
    clock = ledger._clock
    ledger.mark_edited(session_id="s", root="/proj", paths=["app.py"])
    clock.tick()
    ledger.record_run(session_id="s", root="/proj", command="pytest", passed=True, summary="ok")
    st = ledger.status(session_id="s", root="/proj")
    assert st.status == "passed" and st.last_command == "pytest" and st.last_passed is True


def test_failing_run_stays_unverified(ledger):
    clock = ledger._clock
    ledger.mark_edited(session_id="s", root="/proj", paths=["app.py"])
    clock.tick()
    ledger.record_run(session_id="s", root="/proj", command="pytest", passed=False, summary="1 failed")
    st = ledger.status(session_id="s", root="/proj")
    assert st.status == "unverified" and st.last_passed is False


def test_edit_after_a_pass_dirties_again(ledger):
    clock = ledger._clock
    ledger.mark_edited(session_id="s", root="/proj", paths=["app.py"])
    clock.tick(); ledger.record_run(session_id="s", root="/proj", command="pytest", passed=True)
    assert ledger.status(session_id="s", root="/proj").status == "passed"
    clock.tick(); ledger.mark_edited(session_id="s", root="/proj", paths=["app.py"])
    assert ledger.status(session_id="s", root="/proj").status == "unverified"  # stale again


def test_sessions_and_roots_are_isolated(ledger):
    ledger.mark_edited(session_id="a", root="/p1", paths=["x.py"])
    assert ledger.status(session_id="b", root="/p1").status == "not_applicable"
    assert ledger.status(session_id="a", root="/p2").status == "not_applicable"


def test_persists_to_disk(tmp_path):
    db = tmp_path / "nested" / "verify.db"
    lg = VerificationLedger(db, clock=_Clock())
    lg.mark_edited(session_id="s", root="/proj", paths=["a.py"])
    lg.close()
    reopened = VerificationLedger(db, clock=_Clock())
    assert reopened.status(session_id="s", root="/proj").status == "unverified"
    reopened.close()


# ── project verify-command detection ──────────────────────────────────────────


def test_detects_pytest_from_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    assert "pytest" in detect_verify_commands(tmp_path)


def test_detects_pytest_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert detect_verify_commands(tmp_path) == ["pytest"]


def test_detects_npm_test_but_skips_placeholder(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "jest"}}', encoding="utf-8")
    assert "npm test" in detect_verify_commands(tmp_path)

    placeholder = tmp_path / "sub"
    placeholder.mkdir()
    (placeholder / "package.json").write_text(
        '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}',
        encoding="utf-8")
    assert "npm test" not in detect_verify_commands(placeholder)


def test_detects_make_test_target(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    assert "make test" in detect_verify_commands(tmp_path)


def test_empty_project_has_no_commands(tmp_path):
    assert detect_verify_commands(tmp_path) == []


# ── gate helpers ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,verifiable", [
    ("app.py", True), ("src/x.ts", True), ("Makefile", True),
    ("README.md", False), ("LICENSE", False), ("docs/guide.rst", False),
    ("logo.png", False), (".gitignore", False), ("CHANGELOG.md", False),
])
def test_is_verifiable_path(path, verifiable):
    assert is_verifiable_path(path) is verifiable


def test_classify_command_matches_tool_head():
    cmds = ["pytest", "npm test"]
    assert classify_command("cd proj && pytest tests/ -q", cmds) is True
    assert classify_command("npm test --silent", cmds) is True
    assert classify_command("git status", cmds) is False
    assert classify_command("pytest", []) is False


def test_build_nudge_names_command_and_failure():
    from shipit_agent.verify.ledger import VerificationStatus

    st = VerificationStatus(status="unverified", last_command="pytest",
                            last_summary="1 failed: test_x", last_passed=False)
    nudge = build_verify_nudge(st, ["pytest"])
    assert "`pytest`" in nudge
    assert "1 failed: test_x" in nudge
    assert "done" in nudge.lower()
