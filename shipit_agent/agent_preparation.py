"""Skill, delegation, tool, and permission preparation for :class:`Agent`."""

from __future__ import annotations

from typing import Any

from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.skills import Skill, apply_skill, find_relevant_skills
from shipit_agent.skills.tool_bundles import tool_names_for_skills

SkillLike = str | Skill


class AgentPreparationMixin:
    """Build the effective prompt, tools, skills, and permissions for a run."""

    def _resolve_skill_ref(self, skill_ref: SkillLike) -> Skill:
        if isinstance(skill_ref, Skill):
            return skill_ref
        if self.skill_registry is None:
            raise ValueError(
                f"Cannot resolve skill '{skill_ref}' because no skill registry "
                "is configured."
            )
        skill = self.skill_registry.get(skill_ref)
        if skill is None:
            raise ValueError(f"Unknown skill id: {skill_ref}")
        return skill

    def _resolve_skill_refs(self, skill_refs: list[SkillLike]) -> list[Skill]:
        resolved: list[Skill] = []
        seen: set[str] = set()
        for ref in skill_refs:
            skill = self._resolve_skill_ref(ref)
            if skill.id not in seen:
                resolved.append(skill)
                seen.add(skill.id)
        return resolved

    def available_skills(self) -> list[Skill]:
        return self.skill_registry.list() if self.skill_registry is not None else []

    def search_skills(self, query: str) -> list[Skill]:
        if self.skill_registry is None:
            return []
        return self.skill_registry.search(query)

    def add_skill(self, skill: SkillLike) -> Skill:
        resolved = self._resolve_skill_ref(skill)
        if resolved.id not in {item.id for item in self.skills}:
            self.skills.append(resolved)
        return resolved

    def _selected_skills(self, user_prompt: str) -> list[Skill]:
        selected: list[Skill] = []
        seen: set[str] = set()
        candidates = [*self.skills]
        candidates.extend(self._resolve_skill_ref(i) for i in self.default_skill_ids)
        if self.auto_use_skills and self.skill_registry is not None:
            candidates.extend(
                find_relevant_skills(
                    self.skill_registry,
                    user_prompt,
                    max_skills=self.skill_match_limit,
                )
            )
        for skill in candidates:
            if skill.id not in seen:
                selected.append(skill)
                seen.add(skill.id)
        return selected

    def _effective_prompt(self, user_prompt: str) -> str:
        effective = self.prompt
        for skill in self._selected_skills(user_prompt):
            holder = type("PromptHolder", (), {"prompt": effective})()
            apply_skill(holder, skill)
            effective = holder.prompt
        rules = self._rules_block()
        return f"{effective}\n\n{rules}" if rules and rules not in effective else effective

    def _rules_block(self) -> str:
        from shipit_agent.rules import RuleSet, collect_tool_rules

        merged = RuleSet()
        merged.extend(list(self.rules), source="agent")
        merged.rules.extend(self._project_rules or [])
        merged.rules.extend(collect_tool_rules(self.tools))
        if not merged:
            return ""
        names = frozenset(str(getattr(t, "name", "") or "") for t in self.tools)
        return merged.render(tools=names)

    def _delegation_policy(self) -> Any:
        from shipit_agent.delegation import coerce_delegation

        return coerce_delegation(self.delegation)

    def _delegation_warranted(self, user_prompt: str) -> bool:
        policy = self._delegation_policy()
        if policy is None or not isinstance(user_prompt, str) or not user_prompt.strip():
            return False
        try:
            return bool(policy.assess(user_prompt, llm=self.llm))
        except Exception:  # noqa: BLE001
            return True

    def _delegated_prompt(self, user_prompt: str) -> str:
        policy = self._delegation_policy()
        if policy is None or not isinstance(user_prompt, str):
            return user_prompt
        return policy.apply(user_prompt, llm=self.llm)

    def _effective_tools(
        self, user_prompt: str, *, selected_skills: list[Skill] | None = None
    ) -> list[Any]:
        if selected_skills is None:
            selected_skills = self._selected_skills(user_prompt)
        effective = {
            getattr(tool, "name", f"tool_{index}"): tool
            for index, tool in enumerate(self.tools)
        }
        if self.code_mode:
            from shipit_agent.tools.describe_binding import DescribeBindingTool
            from shipit_agent.tools.execute_code import ExecuteCodeTool

            effective.setdefault("execute_code", ExecuteCodeTool())
            effective.setdefault("describe_binding", DescribeBindingTool())

        policy = self._delegation_policy()
        if policy is not None and not self._delegation_warranted(user_prompt):
            policy = None
        if policy is not None and "sub_agent" not in effective:
            if self._auto_sub_agent is None:
                self._auto_sub_agent = policy.build_tool(
                    self.llm, list(effective.values())
                )
            if self._auto_sub_agent is not None:
                effective["sub_agent"] = self._auto_sub_agent

        if selected_skills:
            builtins = get_builtin_tool_map(
                llm=self.llm, project_root=str(self.project_root)
            )
            for name in tool_names_for_skills(selected_skills):
                if name in builtins:
                    effective[name] = builtins[name]
        tools = list(effective.values())
        if self.verifier is not None and hasattr(self.verifier, "wrap_tools"):
            tools = self.verifier.wrap_tools(tools)
        return tools

    def _skill_tool_names(self, selected_skills: list[Skill]) -> list[str]:
        available = {getattr(tool, "name", None) for tool in self.tools}
        names: list[str] = []
        for name in tool_names_for_skills(selected_skills):
            if name not in available and name not in names:
                names.append(name)
        return names

    def _runtime_skill_metadata(
        self, selected_skills: list[Skill]
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        details = [
            {
                "id": skill.id,
                "name": skill.display_name or skill.name or skill.id,
                "description": skill.description,
                "category": skill.category,
            }
            for skill in selected_skills
        ]
        seen = {item["id"] for item in details}
        external = self.metadata.get("selected_skills", [])
        if isinstance(external, list):
            for item in external:
                if not isinstance(item, dict):
                    continue
                skill_id = str(item.get("id", "")).strip()
                if skill_id and skill_id not in seen:
                    details.append(
                        {
                            "id": skill_id,
                            "name": str(item.get("name") or skill_id),
                            "description": str(item.get("description") or ""),
                            "category": str(item.get("category") or ""),
                        }
                    )
                    seen.add(skill_id)
        tools = self._skill_tool_names(selected_skills)
        for name in self.metadata.get("used_skill_tools", []) or []:
            value = str(name).strip()
            if value and value not in tools:
                tools.append(value)
        return [item["id"] for item in details], tools, details

    def _effective_max_iterations(self, selected_skills: list[Skill]) -> int:
        if selected_skills and self.max_iterations <= 12:
            return max(16, self.max_iterations)
        return self.max_iterations

    def _effective_permissions(self) -> Any:
        from shipit_agent.permissions import PermissionEngine, coerce_permissions

        engine = coerce_permissions(self.permissions)
        if engine is None and (
            self.permission_mode != "default" or self.permission_callback is not None
        ):
            engine = PermissionEngine(mode=self.permission_mode)  # type: ignore[arg-type]
        if (
            engine is not None
            and self.permission_callback is not None
            and engine.callback is None
        ):
            engine.callback = self.permission_callback
        return engine
