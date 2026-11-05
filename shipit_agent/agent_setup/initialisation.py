"""Finishing an agent's construction: skills, project rules and memory, delegation and stores.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from uuid import uuid4

from shipit_agent.skills import FileSkillRegistry, SkillRegistry

# Moved methods log under the agent's own name, so filters and levels
# configured for it keep applying.
logger = logging.getLogger("shipit_agent.agent")


class AgentInitMixin:
    """Finishing an agent's construction: skills, project rules and memory, delegation and stores."""

    def __post_init__(self) -> None:
        """Wire up RAG tools/prompts and resolve skill references.

        Called automatically after dataclass init. Three things happen:
        1. If ``rag`` is set, inject its tools and prompt section.
        2. If no ``skill_registry`` is provided, build one from ``skill_source``.
        3. Resolve string skill ids in ``self.skills`` into ``Skill`` objects.
        """
        # These defaults belong to the conversation, not to each short-lived
        # runtime. Otherwise every stream() call starts a new empty session.
        if self.session_id is None:
            self.session_id = str(uuid4())
        self._run_lock = threading.RLock()
        self._async_run_lock = asyncio.Lock()
        if self.session_store is None:
            from shipit_agent.stores import InMemorySessionStore

            self.session_store = InMemorySessionStore()
        if self.memory_store is None:
            from shipit_agent.stores import InMemoryMemoryStore

            self.memory_store = InMemoryMemoryStore()
        if self.stream_queue_maxsize < 1:
            raise ValueError("stream_queue_maxsize must be positive")
        if self.max_task_tokens is not None and (
            type(self.max_task_tokens) is not int or self.max_task_tokens < 1
        ):
            raise ValueError("max_task_tokens must be a positive integer or None")
        if self.max_session_tokens is not None and (
            type(self.max_session_tokens) is not int or self.max_session_tokens < 1
        ):
            raise ValueError("max_session_tokens must be a positive integer or None")
        if self.stream_join_timeout < 0:
            raise ValueError("stream_join_timeout cannot be negative")

        # Fold in any plugins first, so their tools and hooks are present
        # before the rest of construction (RAG, skills) runs. Cheap no-op when
        # the list is empty.
        if self.plugins:
            from shipit_agent.plugins import merge_plugins

            self.tools, self.hooks = merge_plugins(
                self.plugins, tools=self.tools, hooks=self.hooks
            )

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

        # Auto-load SHIPIT.md / AGENTS.md project instructions into the prompt.
        if self.auto_project_memory:
            from shipit_agent.workspace import load_project_memory

            memory = load_project_memory(self.project_root)
            if memory and memory not in self.prompt:
                self.prompt = f"{self.prompt}\n\n{memory}"

        # Build the skill registry from the catalog file if not supplied.
        if self.skill_registry is None and self.skill_source:
            skill_path = Path(self.skill_source)
            if skill_path.exists():
                self.skill_registry = FileSkillRegistry(skill_path)

        # Local SKILL.md files use the standard SKILL.md convention.
        # They override packaged entries with the same id so repository rules
        # remain authoritative without copying the full catalog.
        if self.auto_project_skills:
            from shipit_agent.skills import discover_project_skills

            local_skills = discover_project_skills(self.project_root)
            if local_skills and self.skill_registry is None:
                self.skill_registry = SkillRegistry()
            for skill in local_skills:
                self.skill_registry.register(skill)

        # Cache the file-discovered rules once (.shipit/rules/*.md — the only
        # I/O). AGENTS.md is excluded: it is already folded in as flat project
        # memory above; the rules layer adds the *structured* (scoped,
        # prioritised, tool-level) rules on top. `self.rules` is read live per
        # call, so appending to it after construction still takes effect.
        if self._project_rules is None:
            from shipit_agent.rules import load_project_rules

            self._project_rules = (
                load_project_rules(self.project_root, include_agents_md=False)
                if self.auto_project_rules
                else []
            )

        # Resolve string skill ids → Skill objects (deduplicates by id).
        self.skills = self._resolve_skill_refs(self.skills)

        # Hide tools whose declared dependency is missing — done last, so RAG
        # and skill tools are gated too. Only tools that opted in (declared a
        # requires_command / requires_env / check_fn) can be dropped, so this
        # never removes a plain tool. Skipped tools are recorded for a UI/log.
        if self.gate_unavailable_tools and self.tools:
            from shipit_agent.tools.availability import filter_available

            kept, skipped = filter_available(self.tools)
            if skipped:
                self.tools = kept
                self.metadata.setdefault("gated_tools", skipped)
                logger.info(
                    "gated %d unavailable tool(s): %s",
                    len(skipped),
                    ", ".join(f"{n} ({r})" for n, r in skipped),
                )
