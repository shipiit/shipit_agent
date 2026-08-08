"""The CLI reports health and failure in a form a person can act on.

Both behaviours here replaced something that technically worked: `doctor`
printed the report object's repr, and an uncaught provider error printed a
traceback. Each is checked for the property that matters — that the useful
part is visible, and that the exit code agrees with what was shown.
"""

from __future__ import annotations

import json

import pytest

from shipit_agent.cli import main
from shipit_agent.cli.commands import simple
from shipit_agent.doctor import DoctorCheck, DoctorReport


class _Agent:
    def __init__(self, report: DoctorReport) -> None:
        self._report = report

    def doctor(self) -> DoctorReport:
        return self._report


def _report(*checks: tuple[str, str, str]) -> DoctorReport:
    return DoctorReport(checks=[
        DoctorCheck(name=n, status=s, message=m, details={"why": "detail-" + n})
        for n, s, m in checks
    ])


@pytest.fixture
def patched(monkeypatch):
    def install(report: DoctorReport):
        monkeypatch.setattr(simple, "build_agent", lambda _args: _Agent(report))
    return install


class Args:
    def __init__(self, **kw) -> None:
        self.json = False
        self.__dict__.update(kw)


class TestTheHealthReport:
    def test_it_is_read_as_lines_not_a_repr(self, patched, capsys) -> None:
        patched(_report(("tools", "pass", "58 tools look consistent")))
        simple.cmd_doctor(Args())
        printed = capsys.readouterr().out
        assert "DoctorReport(" not in printed, "printed the dataclass repr"
        assert "58 tools look consistent" in printed

    def test_problems_come_before_what_is_fine(self, patched, capsys) -> None:
        patched(_report(
            ("tools", "pass", "fine"),
            ("llm_provider", "fail", "no API key"),
            ("mcps", "warn", "nothing attached"),
        ))
        simple.cmd_doctor(Args())
        printed = capsys.readouterr().out
        assert (printed.index("no API key") < printed.index("nothing attached")
                < printed.index("fine"))

    def test_a_failing_check_carries_its_details(self, patched, capsys) -> None:
        """The detail is the actionable half — which variable is missing."""
        patched(_report(("llm_provider", "fail", "no API key")))
        simple.cmd_doctor(Args())
        assert "detail-llm_provider" in capsys.readouterr().out

    def test_a_passing_check_does_not(self, patched, capsys) -> None:
        patched(_report(("tools", "pass", "fine")))
        simple.cmd_doctor(Args())
        assert "detail-tools" not in capsys.readouterr().out

    def test_a_failure_is_a_nonzero_exit(self, patched) -> None:
        patched(_report(("llm_provider", "fail", "no API key")))
        assert simple.cmd_doctor(Args()) == 1

    def test_warnings_alone_are_not(self, patched) -> None:
        patched(_report(("mcps", "warn", "nothing attached")))
        assert simple.cmd_doctor(Args()) == 0

    def test_json_reports_the_same_verdict_as_the_terminal(
        self, patched, capsys,
    ) -> None:
        """A script piping --json to jq must not see success either."""
        patched(_report(("llm_provider", "fail", "no API key")))
        code = simple.cmd_doctor(Args(json=True))
        payload = json.loads(capsys.readouterr().out)
        assert code == 1 and payload["passed"] is False


class TestAnUncaughtError:
    def _boom(self, message: str):
        def fn(_args):
            raise RuntimeError(message)
        return fn

    def _run(self, monkeypatch, message: str):
        import argparse

        import shipit_agent.cli as cli

        def parser() -> argparse.ArgumentParser:
            p = argparse.ArgumentParser()
            # A token, so an empty argv never reaches the branch that
            # opens the interactive REPL under `pytest -s`.
            p.add_argument("command")
            p.set_defaults(fn=self._boom(message))
            return p

        monkeypatch.setattr(cli, "build_parser", parser)
        return main(["anything"])

    def test_it_is_summarised_rather_than_traced(
        self, monkeypatch, capsys,
    ) -> None:
        code = self._run(monkeypatch, "the disk is on fire")
        printed = capsys.readouterr().out
        assert code == 1
        assert "the disk is on fire" in printed
        assert "Traceback" not in printed

    def test_a_credential_failure_says_what_to_check(
        self, monkeypatch, capsys,
    ) -> None:
        self._run(monkeypatch, "Error code: 401 - incorrect api key provided")
        assert "shipit doctor" in capsys.readouterr().out

    def test_an_unrelated_failure_does_not(self, monkeypatch, capsys) -> None:
        self._run(monkeypatch, "the disk is on fire")
        assert "shipit doctor" not in capsys.readouterr().out

    def test_debug_still_gets_the_traceback(self, monkeypatch) -> None:
        """Moved, not discarded — the summary is the wrong tool when it is
        the adapter you are debugging."""
        monkeypatch.setenv("SHIPIT_DEBUG", "1")
        with pytest.raises(RuntimeError, match="the disk is on fire"):
            self._run(monkeypatch, "the disk is on fire")

    def test_an_interrupt_is_not_reported_as_a_crash(
        self, monkeypatch, capsys,
    ) -> None:
        import argparse

        import shipit_agent.cli as cli

        def fn(_args):
            raise KeyboardInterrupt

        def parser() -> argparse.ArgumentParser:
            p = argparse.ArgumentParser()
            p.add_argument("command")
            p.set_defaults(fn=fn)
            return p

        monkeypatch.setattr(cli, "build_parser", parser)
        assert main(["anything"]) == 130
        assert "error" not in capsys.readouterr().out
