from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


CheckStatus = str


@dataclass(slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DoctorReport:
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


class AgentDoctor:
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

    def _check_llm(self, llm: Any) -> DoctorCheck:
        provider, details = self._provider_details(llm)
        missing = list(details.pop("missing", []))
        if provider == "shipit":
            return DoctorCheck(
                name="llm_provider",
                status="pass",
                message="ShipitLLM is configured for local development and smoke tests.",
                details=details,
            )
        if missing:
            return DoctorCheck(
                name="llm_provider",
                status="fail",
                message=f"{provider} configuration is missing required environment variables.",
                details={**details, "missing": ", ".join(missing)},
            )
        return DoctorCheck(
            name="llm_provider",
            status="pass",
            message=f"{provider} configuration looks ready.",
            details=details,
        )

    def _check_tools(self, tools: list[Any]) -> DoctorCheck:
        names = [getattr(tool, "name", tool.__class__.__name__) for tool in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            return DoctorCheck(
                name="tools",
                status="fail",
                message="Tool names must be unique.",
                details={"duplicates": ", ".join(duplicates), "tool_count": len(names)},
            )
        if not names:
            return DoctorCheck(
                name="tools",
                status="warn",
                message="Agent has no attached tools.",
                details={"tool_count": 0},
            )

        invalid: list[str] = []
        for tool in tools:
            name = str(getattr(tool, "name", tool.__class__.__name__))
            try:
                schema = tool.schema()
                function = schema.get("function", {})
                parameters = function.get("parameters")
                if function.get("name") != name:
                    invalid.append(f"{name}: schema name mismatch")
                elif not isinstance(parameters, dict):
                    invalid.append(f"{name}: missing parameter schema")
                elif parameters.get("type") not in (None, "object"):
                    invalid.append(f"{name}: parameters must be an object")
            except Exception as exc:  # noqa: BLE001
                invalid.append(f"{name}: {exc}")
        if invalid:
            return DoctorCheck(
                name="tools",
                status="fail",
                message="One or more tools expose invalid callable schemas.",
                details={
                    "tool_count": len(names),
                    "invalid": "; ".join(invalid),
                },
            )

        from shipit_agent.tools.helpers import tool_family

        families: dict[str, int] = {}
        for tool in tools:
            family = tool_family(tool)
            families[family] = families.get(family, 0) + 1
        return DoctorCheck(
            name="tools",
            status="pass",
            message="Tool registry and callable schemas look consistent.",
            details={
                "tool_count": len(names),
                "family_count": len(families),
                "families": ", ".join(
                    f"{name}={count}" for name, count in sorted(families.items())
                ),
                "tools": ", ".join(names[:12]) + (" ..." if len(names) > 12 else ""),
            },
        )

    def _check_skills(self, agent: Any) -> DoctorCheck:
        """Validate the skill catalog and its runtime dependencies."""
        registry = getattr(agent, "skill_registry", None)
        auto_use = bool(getattr(agent, "auto_use_skills", False))
        match_limit = int(getattr(agent, "skill_match_limit", 0) or 0)
        if registry is None:
            return DoctorCheck(
                name="skills",
                status="warn" if auto_use else "pass",
                message=(
                    "Automatic skill selection is enabled but no catalog is loaded."
                    if auto_use
                    else "No skill catalog is configured."
                ),
                details={"catalog_size": 0, "auto_use": auto_use},
            )

        unknown_defaults = [
            skill_id
            for skill_id in getattr(agent, "default_skill_ids", [])
            if registry.get(skill_id) is None
        ]
        if auto_use and match_limit < 1:
            return DoctorCheck(
                name="skills",
                status="fail",
                message="Automatic skill selection needs skill_match_limit >= 1.",
                details={
                    "catalog_size": len(registry),
                    "skill_match_limit": match_limit,
                },
            )
        if unknown_defaults:
            return DoctorCheck(
                name="skills",
                status="fail",
                message="Default skills reference IDs missing from the catalog.",
                details={
                    "catalog_size": len(registry),
                    "unknown_defaults": ", ".join(unknown_defaults),
                },
            )

        from shipit_agent.builtins import get_builtin_tool_map
        from shipit_agent.skills.tool_bundles import validate_tool_bundles

        available_tools = set(
            get_builtin_tool_map(
                llm=agent.llm,
                project_root=str(getattr(agent, "project_root", ".")),
            )
        )
        available_tools.update(
            str(getattr(tool, "name", "")) for tool in getattr(agent, "tools", [])
        )
        bundle_errors = validate_tool_bundles(available_tools)

        active_skills = list(getattr(agent, "skills", []))
        for skill_id in getattr(agent, "default_skill_ids", []):
            skill = registry.get(skill_id)
            if skill is not None and skill not in active_skills:
                active_skills.append(skill)
        missing_tools = sorted(
            {
                f"{skill.id}:{tool_name}"
                for skill in active_skills
                for tool_name in skill.tools
                if tool_name not in available_tools
            }
        )
        attached_mcps = {
            str(getattr(mcp, "name", "")) for mcp in getattr(agent, "mcps", [])
        }
        missing_mcps: list[str] = []
        for skill in active_skills:
            for requirement in skill.mcps:
                name = (
                    str(requirement.get("name") or requirement.get("id") or "")
                    if isinstance(requirement, dict)
                    else str(requirement)
                )
                if name and name not in attached_mcps:
                    missing_mcps.append(f"{skill.id}:{name}")

        problems = [*bundle_errors, *missing_tools, *missing_mcps]
        return DoctorCheck(
            name="skills",
            status="warn" if problems else "pass",
            message=(
                "Skill catalog is loaded, but some runtime dependencies are missing."
                if problems
                else "Skill catalog and runtime dependencies look consistent."
            ),
            details={
                "catalog_size": len(registry),
                "always_on": len(getattr(agent, "skills", [])),
                "default_count": len(getattr(agent, "default_skill_ids", [])),
                "auto_use": auto_use,
                "skill_match_limit": match_limit,
                "bundle_errors": ", ".join(bundle_errors) or "none",
                "missing_tools": ", ".join(missing_tools) or "none",
                "missing_mcps": ", ".join(missing_mcps) or "none",
            },
        )

    def _check_mcps(self, mcps: list[Any]) -> DoctorCheck:
        if not mcps:
            return DoctorCheck(
                name="mcps",
                status="warn",
                message="No MCP servers are attached.",
                details={"mcp_count": 0},
            )
        names = [getattr(mcp, "name", mcp.__class__.__name__) for mcp in mcps]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            return DoctorCheck(
                name="mcps",
                status="fail",
                message="MCP server names must be unique.",
                details={
                    "mcp_count": len(names),
                    "duplicates": ", ".join(duplicates),
                },
            )
        return DoctorCheck(
            name="mcps",
            status="pass",
            message="MCP servers are attached.",
            details={"mcp_count": len(names), "servers": ", ".join(names)},
        )

    def _check_stores(self, agent: Any) -> DoctorCheck:
        details = {
            "memory_store": agent.memory_store.__class__.__name__
            if getattr(agent, "memory_store", None)
            else "None",
            "session_store": agent.session_store.__class__.__name__
            if getattr(agent, "session_store", None)
            else "None",
            "trace_store": agent.trace_store.__class__.__name__
            if getattr(agent, "trace_store", None)
            else "None",
            "session_id": getattr(agent, "session_id", None) or "unset",
            "trace_id": getattr(agent, "trace_id", None) or "unset",
        }
        if not getattr(agent, "memory_store", None) or not getattr(
            agent, "session_store", None
        ):
            return DoctorCheck(
                name="stores",
                status="warn",
                message="Persistent stores are only partially configured.",
                details=details,
            )
        return DoctorCheck(
            name="stores",
            status="pass",
            message="Memory, session, and trace stores are configured.",
            details=details,
        )

    def _check_connectors(self, tools: list[Any], credential_store: Any) -> DoctorCheck:
        connector_tools = [tool for tool in tools if hasattr(tool, "credential_key")]
        if not connector_tools:
            return DoctorCheck(
                name="connectors",
                status="pass",
                message="No connector tools require credentials.",
                details={"connector_count": 0},
            )
        if credential_store is None:
            return DoctorCheck(
                name="connectors",
                status="warn",
                message="Connector tools are attached but no credential store is configured.",
                details={"connector_count": len(connector_tools)},
            )
        from shipit_agent.connections import ConnectionRegistry

        registry = ConnectionRegistry(
            credential_store=credential_store,
            tools=connector_tools,
        )
        connections = {connection.id: connection for connection in registry.all()}
        unavailable: list[str] = []
        connected: list[str] = []
        for tool in connector_tools:
            credential_key = getattr(tool, "credential_key", "")
            provider = getattr(
                tool, "provider", credential_key or getattr(tool, "name", "connector")
            )
            connection = connections.get(credential_key)
            if connection is not None and connection.usable:
                connected.append(f"{provider}:{credential_key}")
            else:
                state = connection.state.value if connection is not None else "missing"
                unavailable.append(f"{provider}:{credential_key}({state})")
        if unavailable:
            return DoctorCheck(
                name="connectors",
                status="warn",
                message="Some connector tools are not ready to use.",
                details={
                    "connector_count": len(connector_tools),
                    "connected": ", ".join(connected) or "none",
                    "unavailable": ", ".join(unavailable),
                },
            )
        return DoctorCheck(
            name="connectors",
            status="pass",
            message="All connector tools have credential records.",
            details={
                "connector_count": len(connector_tools),
                "connected": ", ".join(connected) or "none",
            },
        )

    def _check_iterations(self, agent: Any) -> DoctorCheck:
        max_iterations = int(getattr(agent, "max_iterations", 0) or 0)
        if max_iterations < 1:
            return DoctorCheck(
                name="runtime_limits",
                status="fail",
                message="max_iterations must be at least 1.",
                details={"max_iterations": max_iterations},
            )
        if max_iterations < 3:
            return DoctorCheck(
                name="runtime_limits",
                status="warn",
                message="max_iterations is low for a multi-step tool-using agent.",
                details={"max_iterations": max_iterations},
            )
        return DoctorCheck(
            name="runtime_limits",
            status="pass",
            message="Runtime iteration budget looks reasonable.",
            details={"max_iterations": max_iterations},
        )

    def _check_efficiency(self, agent: Any) -> DoctorCheck:
        """Report whether large/long-running agents use token controls."""
        llm = agent.llm
        class_name = llm.__class__.__name__
        if hasattr(llm, "prompt_caching"):
            cache_mode = "enabled" if llm.prompt_caching else "disabled"
        elif class_name in {"OpenAIChatLLM", "BedrockGemmaChatLLM"}:
            cache_mode = "automatic"
        else:
            cache_mode = "provider-managed or unavailable"

        tool_count = len(getattr(agent, "tools", []))
        code_mode = bool(getattr(agent, "code_mode", False))
        context_window = int(getattr(agent, "context_window_tokens", 0) or 0)
        tool_output_cap = int(getattr(agent, "max_tool_output_chars", 0) or 0)
        recommendations: list[str] = []
        if tool_count > 20 and not code_mode:
            recommendations.append("enable code_mode for progressive tool discovery")
        if context_window <= 0:
            recommendations.append("set context_window_tokens for long runs")
        if tool_count > 20 and tool_output_cap <= 0:
            recommendations.append("set max_tool_output_chars to bound tool context")
        if cache_mode == "disabled":
            recommendations.append("enable prompt_caching on the LLM adapter")

        return DoctorCheck(
            name="efficiency",
            status="warn" if recommendations else "pass",
            message=(
                "Token-efficiency controls can be improved."
                if recommendations
                else "Prompt caching and long-run token controls look ready."
            ),
            details={
                "prompt_caching": cache_mode,
                "code_mode": code_mode,
                "context_window_tokens": context_window,
                "max_tool_output_chars": tool_output_cap,
                "tool_count": tool_count,
                "session_store": agent.session_store.__class__.__name__
                if getattr(agent, "session_store", None)
                else "runtime default",
                "memory_store": agent.memory_store.__class__.__name__
                if getattr(agent, "memory_store", None)
                else "runtime default",
                "recommendations": "; ".join(recommendations) or "none",
            },
        )

    def _provider_details(self, llm: Any) -> tuple[str, dict[str, Any]]:
        class_name = llm.__class__.__name__
        model = getattr(llm, "model", "")
        provider = "unknown"
        missing: list[str] = []

        def env_present(*names: str) -> bool:
            return any(self.env.get(name) for name in names)

        if class_name in {"SimpleEchoLLM", "ShipitLLM"}:
            provider = "shipit"
        elif class_name == "OpenAIChatLLM":
            provider = "openai"
            if not (getattr(llm, "api_key", None) or env_present("OPENAI_API_KEY")):
                missing.append("OPENAI_API_KEY")
        elif class_name == "AnthropicChatLLM":
            provider = "anthropic"
            if not (getattr(llm, "api_key", None) or env_present("ANTHROPIC_API_KEY")):
                missing.append("ANTHROPIC_API_KEY")
        elif class_name in {
            "LiteLLMChatLLM",
            "BedrockChatLLM",
            "GeminiChatLLM",
            "GroqChatLLM",
            "TogetherChatLLM",
            "OllamaChatLLM",
        }:
            provider, missing = self._litellm_requirements(
                class_name=class_name, model=str(model)
            )

        return provider, {
            "class_name": class_name,
            "model": model or "n/a",
            "missing": missing,
        }

    def _litellm_requirements(
        self, *, class_name: str, model: str
    ) -> tuple[str, list[str]]:
        lower_model = model.lower()
        if class_name == "BedrockChatLLM" or lower_model.startswith("bedrock/"):
            provider = "bedrock"
            if not (
                self.env.get("AWS_PROFILE")
                or self.env.get("AWS_REGION_NAME")
                or self.env.get("AWS_DEFAULT_REGION")
            ):
                return provider, [
                    "AWS_REGION_NAME or AWS_DEFAULT_REGION or AWS_PROFILE"
                ]
            return provider, []
        if class_name == "GeminiChatLLM" or lower_model.startswith("gemini/"):
            return "gemini", [] if (
                self.env.get("GEMINI_API_KEY") or self.env.get("GOOGLE_API_KEY")
            ) else ["GEMINI_API_KEY or GOOGLE_API_KEY"]
        if class_name == "GroqChatLLM" or lower_model.startswith("groq/"):
            return "groq", [] if self.env.get("GROQ_API_KEY") else ["GROQ_API_KEY"]
        if class_name == "TogetherChatLLM" or lower_model.startswith("together_ai/"):
            return "together", [] if (
                self.env.get("TOGETHERAI_API_KEY") or self.env.get("TOGETHER_API_KEY")
            ) else ["TOGETHERAI_API_KEY or TOGETHER_API_KEY"]
        if class_name == "OllamaChatLLM" or lower_model.startswith("ollama/"):
            return "ollama", []
        return "litellm", []
