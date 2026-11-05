"""Building and running one sub-agent: inherited tools, the child agent, and its streamed run.

Mixed into :class:`~shipit_agent.tools.sub_agent.sub_agent_tool.SubAgentTool`.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext

from .defined import llm_for, tools_for
from .result import (
    _NEVER_INHERITED,
    DEPTH_STATE_KEY,
    EVENT_SINK_KEY,
    PARENT_STATE_KEY,
    SubAgentResult,
    _state,
)


class ChildRunMixin:
    """Building and running one sub-agent: inherited tools, the child agent, and its streamed run."""

    def _inherited_tools(self, context: ToolContext) -> list[Any]:
        """The parent's tools, minus this tool and the never-inherited set.

        Removing ``sub_agent`` itself is belt-and-braces alongside the depth
        cap: a child that cannot see the tool cannot try to use it.
        """
        if self.tools is not None:
            return list(self.tools)
        parent = _state(context, "state").get(PARENT_STATE_KEY) or {}
        inherited = []
        for tool in parent.get("tools") or []:
            tool_name = getattr(tool, "name", "")
            if tool_name == self.name or tool_name in _NEVER_INHERITED:
                continue
            inherited.append(tool)
        return inherited

    def _build_agent(self, context: ToolContext, agent_type: str, depth: int) -> Any:
        from shipit_agent.agent import Agent

        parent = _state(context, "state").get(PARENT_STATE_KEY) or {}
        tools = self._inherited_tools(context)

        kwargs: dict[str, Any] = {
            "llm": self.llm,
            "tools": tools,
            "max_iterations": self.max_iterations,
            # A subagent's whole value is a clean context; auto-matching
            # skills against its task would refill it with guidance the
            # parent already applied.
            "auto_use_skills": False,
            # The control plane is inherited verbatim. Delegation must not be
            # a way around a policy the parent is subject to.
            "permissions": parent.get("permissions"),
            "approvals": parent.get("approvals"),
            "guardrails": parent.get("guardrails"),
            "project_root": parent.get("project_root", "."),
        }

        definition = self.agents.get(agent_type.lower()) if agent_type else None
        if definition is not None:
            child = Agent(
                **{
                    **kwargs,
                    "llm": llm_for(self.llm, definition),
                    "tools": tools_for(definition, tools),
                    "prompt": definition.prompt,
                }
            )
            child.metadata = {**child.metadata, DEPTH_STATE_KEY: depth + 1}
            return child

        agent = None
        if agent_type:
            try:
                # for_role sets its own metadata (role, category), so depth is
                # stamped afterwards rather than passed in.
                agent = Agent.for_role(agent_type, **kwargs)
            except ValueError:
                # An unknown role is the model guessing; fall through to the
                # general-purpose agent rather than losing the delegation.
                agent = None
        if agent is None:
            agent = Agent(prompt=self.prompt, **kwargs)
        else:
            # for_role re-adds its role's full builtin set on top of the
            # inherited `tools`, which quietly re-grants write_file/bash and
            # even ask_user_async to a child that was meant to be read-only.
            # Constrain it back to what the parent actually holds, minus the
            # never-inherited human-interaction tools — the control plane is
            # inherited, so delegation must not widen the toolset.
            allowed = {getattr(t, "name", "") for t in tools}
            agent.tools = [
                t
                for t in agent.tools
                if getattr(t, "name", "") in allowed
                and getattr(t, "name", "") not in _NEVER_INHERITED
            ]
        agent.metadata = {**agent.metadata, DEPTH_STATE_KEY: depth + 1}
        return agent

    def _run_task(
        self,
        *,
        task: str,
        task_context: str,
        agent_type: str,
        context: ToolContext,
        depth: int,
        task_id: str | None = None,
    ) -> SubAgentResult:
        result = SubAgentResult(task=task, output="", agent_type=agent_type or None)
        label = agent_type or "sub-agent"
        sink = _state(context, "state").get(EVENT_SINK_KEY)
        hooks = (_state(context, "state").get(PARENT_STATE_KEY) or {}).get("hooks")
        if hooks is not None:
            allowed, refusal, extra = hooks.run_subagent_start(agent_type or "", task)
            if not allowed:
                result.error = f"Delegation refused: {refusal}"
                return result
            if extra:
                task_context = f"{task_context}\n\n{extra}".strip()

        try:
            agent = self._build_agent(context, agent_type, depth)
            if task_id is not None:
                # Kept so stop_task can reach a child that is already running.
                with self._lock:
                    self._children[task_id] = agent
            brief = task if not task_context else f"{task}\n\nContext:\n{task_context}"
            if sink is None:
                run = agent.run(brief)
                summary = run.summary()
                output, metadata = run.output, run.metadata
            else:
                # Stream so the child's work appears in the parent's
                # transcript as it happens, rather than the parent showing
                # one opaque row and a result minutes later.
                output, metadata, summary = self._stream_child(
                    agent, brief, sink=sink, label=label, task=task
                )
        except Exception as exc:  # noqa: BLE001 — reported to the parent as data
            result.error = f"{type(exc).__name__}: {exc}"
            if hooks is not None:
                hooks.run_subagent_stop(agent_type or "", task, "", result.error)
            return result
        finally:
            if task_id is not None:
                with self._lock:
                    self._children.pop(task_id, None)

        result.output = output or ""
        if hooks is not None:
            hooks.run_subagent_stop(agent_type or "", task, result.output, "")
        result.iterations = int(summary.get("iterations") or 0)
        result.tool_calls = int(summary.get("tool_calls") or 0)
        result.usage = dict(summary.get("usage") or {})
        result.gave_up = bool(metadata.get("gave_up"))
        result.give_up_reason = str(metadata.get("give_up_reason") or "")
        return result

    @staticmethod
    def _stream_child(
        agent: Any, brief: str, *, sink: Any, label: str, task: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Run the child, forwarding its events to the parent's sink."""
        from shipit_agent.core.models import AgentResult

        events: list[Any] = []
        output = ""
        for event in agent.stream(brief):
            events.append(event)
            if event.type == "run_completed":
                output = str(event.payload.get("output", "") or "")
            # Mark the origin so a renderer can nest it, and so the parent's
            # own rows are never confused with a child's.
            try:
                sink(event, label, task)
            except Exception:
                # A subscriber must never be able to break the delegation.
                pass

        run = AgentResult(output=output, messages=[], events=events)
        return output, dict(agent.metadata), run.summary()
