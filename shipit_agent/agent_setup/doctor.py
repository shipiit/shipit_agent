"""Health checks for an agent's configuration: model credentials, tools, MCP servers and settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .checks_run import _RunChecks
from .checks_setup import _SetupChecks
from .checks_tools import _ToolSkillChecks
from .doctor_types import CheckStatus as CheckStatus
from .doctor_types import DoctorCheck as DoctorCheck


@dataclass(slots=True)
class DoctorReport:
    """Every check from one doctor run, with whether the agent passed overall."""
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    @property
    def failures(self) -> list[DoctorCheck]:
        return [check for check in self.checks if check.status == "fail"]

    @property
    def warnings(self) -> list[DoctorCheck]:
        return [check for check in self.checks if check.status == "warn"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "check_count": len(self.checks),
            "failure_count": len(self.failures),
            "warning_count": len(self.warnings),
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "message": check.message,
                    "details": dict(check.details),
                }
                for check in self.checks
            ],
        }

    def to_markdown(self) -> str:
        lines = [
            "# SHIPIT Agent Doctor Report",
            "",
            f"- Passed: {'yes' if self.passed else 'no'}",
            f"- Checks: {len(self.checks)}",
            f"- Failures: {len(self.failures)}",
            f"- Warnings: {len(self.warnings)}",
            "",
        ]
        for check in self.checks:
            status = {
                "pass": "PASS",
                "warn": "WARN",
                "fail": "FAIL",
            }.get(check.status, check.status.upper())
            lines.append(f"## {status} {check.name}")
            lines.append(check.message)
            if check.details:
                for key, value in sorted(check.details.items()):
                    lines.append(f"- {key}: {value}")
            lines.append("")
        return "\n".join(lines).strip()


class AgentDoctor(_ToolSkillChecks, _SetupChecks, _RunChecks):
    """Inspect an agent's configuration and report what is missing or misconfigured."""
    def __init__(self, *, env: dict[str, str] | None = None) -> None:
        self.env = dict(os.environ if env is None else env)

    def inspect(self, agent: Any) -> DoctorReport:
        checks = [
            self._check_llm(agent.llm),
            self._check_tools(agent.tools),
            self._check_skills(agent),
            self._check_mcps(agent.mcps),
            self._check_stores(agent),
            self._check_connectors(
                agent.tools, getattr(agent, "credential_store", None)
            ),
            self._check_efficiency(agent),
            self._check_iterations(agent),
        ]
        return DoctorReport(checks=checks)
