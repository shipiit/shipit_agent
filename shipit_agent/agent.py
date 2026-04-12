from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.builtins import get_builtin_tool_map, get_builtin_tools
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.doctor import AgentDoctor, DoctorReport
from shipit_agent.integrations import CredentialStore
from shipit_agent.models import AgentResult, Message
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.reasoning import ReasoningResult, ReasoningRuntime
from shipit_agent.runtime import AgentRuntime
from shipit_agent.skills import (
    FileSkillRegistry,
    Skill,
    SkillRegistry,
    apply_skill,
    find_relevant_skills,
)
from shipit_agent.skills.tool_bundles import tool_names_for_skills
from shipit_agent.stores import MemoryStore, SessionStore
from shipit_agent.tracing import TraceStore

DEFAULT_SKILLS_PATH = Path(__file__).resolve().parent / "skills" / "skills.json"
SkillLike = str | Skill


@dataclass(slots=True)
class Agent:
    llm: Any
    prompt: str = DEFAULT_AGENT_PROMPT
    tools: list[Any] = field(default_factory=list)
    mcps: list[Any] = field(default_factory=list)
    name: str = "shipit"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[Message] = field(default_factory=list)
    memory_store: MemoryStore | None = None
    session_store: SessionStore | None = None
    credential_store: CredentialStore | None = None
    trace_store: TraceStore | None = None
    session_id: str | None = None
    trace_id: str | None = None
    max_iterations: int = 4
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)
    parallel_tool_execution: bool = False
    hooks: Any = None
    context_window_tokens: int = 0
    replan_interval: int = 0
    rag: Any = None
    project_root: str | Path = "/tmp"
    skill_registry: SkillRegistry | None = None
    skill_source: str | Path | None = DEFAULT_SKILLS_PATH
    auto_use_skills: bool = True
    skills: list[SkillLike] = field(default_factory=list)
    default_skill_ids: list[str] = field(default_factory=list)
    skill_match_limit: int = 3

    def __post_init__(self) -> None:
        if self.rag is not None:
            # Auto-wire RAG tools and augment the prompt once per Agent.
            existing_names = {getattr(t, "name", None) for t in self.tools}
            for tool in self.rag.as_tools():
                if tool.name not in existing_names:
                    self.tools.append(tool)
                    existing_names.add(tool.name)
            rag_section = self.rag.prompt_section()
            if rag_section and rag_section not in self.prompt:
                self.prompt = f"{self.prompt}\n\n{rag_section}"
        if self.skill_registry is None and self.skill_source:
            skill_path = Path(self.skill_source)
            if skill_path.exists():
                self.skill_registry = FileSkillRegistry(skill_path)
        self.skills = self._resolve_skill_refs(self.skills)

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        prompt: str = DEFAULT_AGENT_PROMPT,
        name: str = "shipit",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        workspace_root: str = ".shipit_workspace",
        web_search_provider: str = "duckduckgo",
        web_search_api_key: str | None = None,
        web_search_config: dict[str, Any] | None = None,
        mcps: list[Any] | None = None,
        rag: Any = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> "Agent":
        """Build an Agent that ships with the full built-in tool catalogue.

        ``tools=`` may be passed alongside the builtins — user tools are
        merged in and any tool whose ``name`` collides with a builtin
        replaces the builtin (last-write-wins).
        """
        builtin_tools = get_builtin_tools(
            llm=llm,
            project_root=str(kwargs.get("project_root", "/tmp")),
            workspace_root=workspace_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
        )
        merged: dict[str, Any] = {}
        for tool in (*builtin_tools, *(tools or [])):
            tool_name = getattr(tool, "name", None)
            if tool_name:
                merged[tool_name] = tool
        return cls(
            llm=llm,
            prompt=prompt,
            tools=list(merged.values()),
            mcps=list(mcps or []),
            name=name,
            description=description,
            metadata=metadata or {},
            rag=rag,
            **kwargs,
        )

    def _resolve_skill_ref(self, skill_ref: SkillLike) -> Skill:
        if isinstance(skill_ref, Skill):
            return skill_ref
        if self.skill_registry is None:
            raise ValueError(
                f"Cannot resolve skill '{skill_ref}' because no skill registry is configured."
            )
        skill = self.skill_registry.get(skill_ref)
        if skill is None:
            raise ValueError(f"Unknown skill id: {skill_ref}")
        return skill

    def _resolve_skill_refs(self, skill_refs: list[SkillLike]) -> list[Skill]:
        resolved: list[Skill] = []
        seen_ids: set[str] = set()
        for skill_ref in skill_refs:
            skill = self._resolve_skill_ref(skill_ref)
            if skill.id in seen_ids:
                continue
            resolved.append(skill)
            seen_ids.add(skill.id)
        return resolved

    def available_skills(self) -> list[Skill]:
        if self.skill_registry is None:
            return []
        return self.skill_registry.list()

    def search_skills(self, query: str) -> list[Skill]:
        if self.skill_registry is None:
            return []
        return self.skill_registry.search(query)

    def add_skill(self, skill: SkillLike) -> Skill:
        resolved = self._resolve_skill_ref(skill)
        if resolved.id not in {existing.id for existing in self.skills}:
            self.skills.append(resolved)
        return resolved

    def _selected_skills(self, user_prompt: str) -> list[Skill]:

        selected: list[Skill] = []
        seen_ids: set[str] = set()
        for skill in self.skills:
            if skill.id not in seen_ids:
                selected.append(skill)
                seen_ids.add(skill.id)
        for skill_id in self.default_skill_ids:
            skill = self._resolve_skill_ref(skill_id)
            if skill.id not in seen_ids:
                selected.append(skill)
                seen_ids.add(skill.id)

        if self.auto_use_skills and self.skill_registry is not None:
            for skill in find_relevant_skills(
                self.skill_registry,
                user_prompt,
                max_skills=self.skill_match_limit,
            ):
                if skill.id in seen_ids:
                    continue
                selected.append(skill)
                seen_ids.add(skill.id)
        return selected

    def _effective_prompt(self, user_prompt: str) -> str:
        effective = self.prompt
        for skill in self._selected_skills(user_prompt):
            holder = type("PromptHolder", (), {"prompt": effective})()
            apply_skill(holder, skill)
            effective = holder.prompt
        return effective

    def _effective_tools(
        self, user_prompt: str, *, selected_skills: list[Skill] | None = None
    ) -> list[Any]:
        if selected_skills is None:
            selected_skills = self._selected_skills(user_prompt)
        effective: dict[str, Any] = {
            getattr(tool, "name", f"tool_{index}"): tool
            for index, tool in enumerate(self.tools)
        }
        if not selected_skills:
            return list(effective.values())

        builtin_tool_map = get_builtin_tool_map(
            llm=self.llm,
            project_root=str(self.project_root),
        )
        for tool_name in tool_names_for_skills(selected_skills):
            tool = builtin_tool_map.get(tool_name)
            if tool is not None:
                effective[tool_name] = tool
        return list(effective.values())

    def _skill_tool_names(self, selected_skills: list[Skill]) -> list[str]:
        available_names = {getattr(tool, "name", None) for tool in self.tools}
        names: list[str] = []
        seen: set[str] = set()
        for tool_name in tool_names_for_skills(selected_skills):
            if tool_name in available_names or tool_name in seen:
                continue
            names.append(tool_name)
            seen.add(tool_name)
        return names

    def _effective_max_iterations(self, selected_skills: list[Skill]) -> int:
        """Boost max_iterations when skills inject extra tools.

        Skills bring additional tools that the agent needs more turns to
        utilise effectively.  When the caller left ``max_iterations`` at
        the default (4), we raise it to ``max(8, default)`` so the agent
        can complete multi-step skill-driven workflows without cutting
        off early.  An explicit override is always respected.
        """
        if selected_skills and self.max_iterations <= 4:
            return max(8, self.max_iterations)
        return self.max_iterations

    def run(self, user_prompt: str, *, output_schema: Any = None) -> AgentResult:
        # Append schema instructions to the USER prompt (not system prompt)
        # so the model can still use tools normally and only formats the
        # final answer as JSON. Bedrock returns empty content when schema
        # instructions pollute the system prompt.
        effective_user_prompt = user_prompt
        if output_schema:
            from shipit_agent.structured import build_schema_prompt

            effective_user_prompt = user_prompt + build_schema_prompt(output_schema)

        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(user_prompt, selected_skills=selected_skills)
        skill_tool_names = self._skill_tool_names(selected_skills)

        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self.trace_store,
            trace_id=self.trace_id,
            max_iterations=self._effective_max_iterations(selected_skills),
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
            parallel_tool_execution=self.parallel_tool_execution,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            replan_interval=self.replan_interval,
        )
        state, response = runtime.run(effective_user_prompt)

        parsed = None
        if output_schema and response.content:
            try:
                from shipit_agent.structured import parse_structured_output

                parsed = parse_structured_output(response.content, output_schema)
            except Exception:
                parsed = None

        rag_sources = self.rag.end_run() if self.rag is not None else []

        result_metadata = dict(response.metadata)
        result_metadata["used_skills"] = [skill.id for skill in selected_skills]
        result_metadata["used_skill_tools"] = skill_tool_names

        return AgentResult(
            output=response.content,
            messages=state.messages,
            events=state.events,
            tool_results=state.tool_results,
            metadata=result_metadata,
            parsed=parsed,
            rag_sources=rag_sources,
        )

    def stream(self, user_prompt: str):
        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(user_prompt, selected_skills=selected_skills)

        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                "used_skills": [skill.id for skill in selected_skills],
                "used_skill_tools": self._skill_tool_names(selected_skills),
                **self.metadata,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self.trace_store,
            trace_id=self.trace_id,
            max_iterations=self._effective_max_iterations(selected_skills),
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
            parallel_tool_execution=self.parallel_tool_execution,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            replan_interval=self.replan_interval,
        )
        for event in runtime.stream(user_prompt):
            yield event

        if self.rag is not None:
            from shipit_agent.models import AgentEvent

            sources = self.rag.end_run()
            if sources:
                yield AgentEvent(
                    type="rag_sources",
                    message=f"Captured {len(sources)} RAG source(s)",
                    payload={"sources": [s.to_dict() for s in sources]},
                )

    def doctor(self, *, env: dict[str, str] | None = None) -> DoctorReport:
        return AgentDoctor(env=env).inspect(self)

    def chat_session(
        self, *, session_id: str, trace_id: str | None = None
    ) -> AgentChatSession:
        return AgentChatSession(agent=self, session_id=session_id, trace_id=trace_id)

    def reason(
        self,
        prompt: str,
        *,
        observations: list[str] | None = None,
        options: list[str] | None = None,
        criteria: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> ReasoningResult:
        return ReasoningRuntime(self).run(
            prompt,
            observations=observations,
            options=options,
            criteria=criteria,
            constraints=constraints,
        )
