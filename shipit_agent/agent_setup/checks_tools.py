"""AgentDoctor checks for tools and skills."""

from __future__ import annotations

from typing import Any

from .doctor_types import DoctorCheck


class _ToolSkillChecks:
    """AgentDoctor checks for tools and skills."""

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

        from shipit_agent.agent_setup.builtins import get_builtin_tool_map
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
