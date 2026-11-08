"""Scheduled-agent configuration, the factory that builds the agent, and a run's result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class ScheduleResult:
    """Result envelope for a scheduled agent execution."""

    agent_result: Any
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduledAgentConfig:
    """Serializable agent/runtime selection for one scheduled job."""

    provider: str | None = None
    model: str | None = None
    role: str | None = None
    project_root: str | None = None
    runtime: str = "project"  # project | builtins | role
    optimized: bool = True
    permission_mode: str = "default"
    guardrails: str | None = "standard"
    mcps: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    auto_use_skills: bool = True
    max_iterations: int | None = None
    stream_events: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.runtime not in {"project", "builtins", "role"}:
            raise ValueError("runtime must be project, builtins, or role")
        if self.permission_mode not in {"default", "acceptEdits", "plan", "bypass"}:
            raise ValueError(
                "permission_mode must be default, acceptEdits, plan, or bypass"
            )
        if self.guardrails not in {None, "standard", "strict"}:
            raise ValueError("guardrails must be standard, strict, or None")
        if self.runtime == "role" and not self.role:
            raise ValueError("role runtime requires a role")
        if self.max_iterations is not None and self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "project_root": self.project_root,
            "runtime": self.runtime,
            "optimized": self.optimized,
            "permission_mode": self.permission_mode,
            "guardrails": self.guardrails,
            "mcps": list(self.mcps),
            "connections": list(self.connections),
            "skills": list(self.skills),
            "auto_use_skills": self.auto_use_skills,
            "max_iterations": self.max_iterations,
            "stream_events": self.stream_events,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ScheduledAgentConfig":
        raw = dict(value or {})
        known = {field.name for field in cls.__dataclass_fields__.values()}
        config = cls(**{key: item for key, item in raw.items() if key in known})
        config.mcps = [str(name) for name in config.mcps]
        config.connections = [str(name) for name in config.connections]
        config.skills = [str(name) for name in config.skills]
        config.metadata = dict(config.metadata or {})
        config.validate()
        return config


@dataclass(slots=True)
class ScheduledAgentFactory:
    """Build isolated agents from persisted scheduled-job configuration."""

    llm_factory: Callable[[str | None, str | None], Any]
    mcp_factory: Callable[[str], Any] | None = None
    default_provider: str | None = None
    default_model: str | None = None
    default_project_root: str | None = None
    default_mcps: list[str] = field(default_factory=list)
    credential_store: Any = None

    def __call__(self, config: ScheduledAgentConfig) -> Any:
        from pathlib import Path

        from shipit_agent import Agent, Guardrails, connect_mcp

        config.validate()
        provider = config.provider or self.default_provider
        model = config.model or self.default_model
        project_root = (
            config.project_root or self.default_project_root or str(Path.cwd())
        )
        llm = self.llm_factory(provider, model)

        guardrails = None
        if config.guardrails == "strict":
            guardrails = Guardrails.strict()
        elif config.guardrails == "standard":
            guardrails = Guardrails.standard()

        attach_mcp = self.mcp_factory or connect_mcp
        mcp_names = config.mcps or self.default_mcps
        common: dict[str, Any] = {
            "guardrails": guardrails,
            "mcps": [attach_mcp(name) for name in mcp_names],
            "permission_mode": config.permission_mode,
            "default_skill_ids": list(config.skills),
            "auto_use_skills": config.auto_use_skills,
            "metadata": {
                **dict(config.metadata),
                "scheduled": True,
                "required_connections": list(config.connections),
            },
        }
        if self.credential_store is not None:
            common["credential_store"] = self.credential_store
        if config.max_iterations is not None:
            common["max_iterations"] = config.max_iterations

        if config.runtime == "role":
            return Agent.for_role(
                config.role or "",
                llm=llm,
                project_root=project_root,
                **common,
            )
        if config.runtime == "builtins":
            return Agent.with_builtins(
                llm=llm,
                project_root=project_root,
                optimized=config.optimized,
                **common,
            )
        return Agent.for_project(
            llm=llm,
            project_root=project_root,
            optimized=config.optimized,
            **common,
        )

