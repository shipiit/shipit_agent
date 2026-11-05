"""``sub_agent`` — delegate a task to a real agent, not a single completion.

This used to be a lie. The old implementation called ``llm.complete()`` once,
with ``messages=[]`` and ``tools=[]``, and returned the text. No loop, no
tools, no agent — a sub-agent that could not read a file or run a command.

A subagent is worth having for three reasons, and all three need a real loop:

- **Context isolation.** A search that reads forty files should return three
  sentences to the parent, not forty files. The parent's context stays clean.
- **Parallelism.** Independent work runs at once (``background=true`` → task
  id → ``collect``), instead of serially in one thread of thought.
- **Focus.** A narrower prompt and a narrower toolset beat a general agent
  told to please concentrate.

**A subagent can never do more than its parent.** Its tools are a subset of
the parent's, and it inherits the parent's permission engine, approval queue
and guardrails verbatim. Delegation is not a privilege-escalation path — if
the parent must ask before writing a file, so must the child.

Agent types come from the built-in :class:`~shipit_agent.agents.AgentRegistry`
(40+ roles), so ``agent_type="researcher"`` gets the researcher's prompt and
tool selection without anyone declaring it twice.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from itertools import count
from typing import Any

from shipit_agent.agents.subagent_definitions import SubagentDefinition
from shipit_agent.llms.base import LLM
from shipit_agent.tools.base import ToolContext, ToolOutput

from .background import BackgroundTasksMixin
from .child import ChildRunMixin
from .defined import llm_for
from .prompt import SUB_AGENT_SYSTEM_PROMPT
from .result import (
    DEFAULT_MAX_ITERATIONS,
    DEPTH_STATE_KEY,
    EVENT_SINK_KEY,
    MAX_DEPTH,
    PARENT_STATE_KEY,
    SubAgentResult,
    _state,
)
from .schema import sub_agent_schema

__all__ = [
    "SubAgentTool",
    "SubAgentResult",
    "PARENT_STATE_KEY",
    "DEPTH_STATE_KEY",
    "EVENT_SINK_KEY",
]


class SubAgentTool(ChildRunMixin, BackgroundTasksMixin):
    """Delegate a focused task to a real agent — foreground or background."""

    read_only = False

    def __init__(
        self,
        llm: LLM,
        *,
        name: str = "sub_agent",
        description: str = (
            "Delegate a focused task to a sub-agent with its own context and "
            "tools. Use for searches that would flood your context, or for "
            "independent work you can run in parallel."
        ),
        prompt: str | None = None,
        max_workers: int = 4,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        tools: list[Any] | None = None,
        #: Per-subagent wall-clock ceiling. A delegated run without one can
        #: hang the parent forever — ``future.result()`` blocks with no
        #: deadline, and a hung non-daemon worker also wedges interpreter
        #: exit. ``None`` keeps the old unbounded behaviour.
        timeout: float | None = None,
        #: Named sub-agents the parent may pick with ``agent_type``.
        agents: dict[str, SubagentDefinition] | None = None,
    ) -> None:
        self.llm = llm
        self.agents = dict(agents or {})
        self.timeout = timeout
        self.name = name
        self.description = description
        # The CHILD's system prompt (final-report contract), not the parent-
        # facing "when to delegate" text — those were swapped, so every
        # general-purpose sub-agent used to be told how to delegate.
        self.prompt = prompt or SUB_AGENT_SYSTEM_PROMPT
        self.max_iterations = max_iterations
        # An explicit toolset overrides inheritance entirely — for callers who
        # want a subagent narrower than any subset the parent happens to hold.
        self.tools = tools
        self.prompt_instructions = (
            "Delegate when a task would flood your context (a wide search, "
            "a long file to summarize) or when several independent pieces "
            "of work can run at once.\n\n"
            "Do NOT delegate work you can do with one tool call. Reading a "
            "file, listing a directory, one lookup, or writing the answer "
            "are all faster done yourself, and a sub-agent doing them costs "
            "an extra model call and loses everything it saw. If you find "
            "yourself delegating every step, use the tools directly "
            "instead.\n\n"
            "The sub-agent starts fresh: it sees only the `task` and `details` "
            "you give it, not your conversation. Say what you want back.\n\n"
            "`agent_type` picks a specialist (researcher, code-reviewer, "
            "data-analyst, …); omit it for a general-purpose one. "
            "`background=true` returns a task id immediately so you can keep "
            "working; `collect=\"<id>\"` fetches the result. Anything you "
            "start in the background must be collected in this same turn — "
            "the run ends with your answer, and there is no later turn in "
            "which results arrive on their own."
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sub_agent"
        )
        self._tasks: dict[str, Future[SubAgentResult]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._children: dict[str, Any] = {}
        self._task_ids = count(1)
        self._lock = threading.Lock()

    def llm_for(self, definition: SubagentDefinition) -> Any:
        """The model a defined sub-agent runs with."""
        return llm_for(self.llm, definition)

    def close(self) -> None:
        """Release the thread pool, cancelling anything still queued."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:  # best-effort; GC order is not guaranteed
        try:
            self.close()
        except Exception:
            pass

    # ── schema ───────────────────────────────────────────────────────────

    def schema(self) -> dict[str, Any]:
        return sub_agent_schema(self.name, self.description, self.agents)

    # ── building the child ───────────────────────────────────────────────

    # ── run ──────────────────────────────────────────────────────────────

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        collect = str(kwargs.get("collect", "")).strip()
        if collect:
            return self._collect(collect)

        task = str(kwargs.get("task", "")).strip()
        if not task:
            return ToolOutput(
                text=(
                    "Provide `task` to delegate, or `collect` to fetch a "
                    "background result."
                ),
                metadata={"ok": False},
            )
        # A sub-agent starts with no memory of this conversation: the task
        # IS its entire brief. Punctuation is not one. Observed on Gemma 4
        # reaching for delegation reflexively — `sub_agent(task=",")`, which
        # the tool accepted and which burned a model call to return an
        # error. A guard is worth more here than an instruction, because the
        # instruction is only advice.
        if not any(character.isalnum() for character in task):
            return ToolOutput(
                text=(
                    f"There is nothing to delegate in {task!r}. A "
                    f"sub-agent sees none of this conversation, so the task "
                    f"has to name what to do and what to return. If the "
                    f"work is one lookup or one file, do it yourself with "
                    f"the tool for it — that is faster than delegating and "
                    f"you keep the result."
                ),
                metadata={"ok": False, "error": "task_too_thin"},
            )

        depth = int(_state(context, "metadata").get(DEPTH_STATE_KEY, 0) or 0)
        if depth >= MAX_DEPTH:
            return ToolOutput(
                text=(
                    f"Delegation is capped at {MAX_DEPTH} levels and you are "
                    f"already at level {depth}. Do this task yourself."
                ),
                metadata={"ok": False, "error": "max_depth", "depth": depth},
            )

        # Accept the old name too, in case a model or caller still sends it —
        # though ToolRunner strips it, so it will only ever arrive from a
        # direct call.
        task_context = str(
            kwargs.get("details") or kwargs.get("task_context") or ""
        ).strip()
        agent_type = str(kwargs.get("agent_type", "")).strip()

        if kwargs.get("background"):
            with self._lock:
                task_id = f"task-{next(self._task_ids)}"
                self._tasks[task_id] = self._executor.submit(
                    self._run_task,
                    task=task,
                    task_context=task_context,
                    agent_type=agent_type,
                    context=context,
                    depth=depth,
                    task_id=task_id,
                )
                self._meta[task_id] = {"task": task, "agent_type": agent_type or None}
            return ToolOutput(
                text=(
                    f"Started {task_id}"
                    + (f" ({agent_type})" if agent_type else "")
                    + f": {task}\n"
                    f'Keep working, then call this tool with collect="{task_id}" '
                    f'(or collect="all") to fetch the result.\n'
                    f"You must collect it BEFORE you answer. There is no "
                    f"later: this turn ends when you write your answer, and "
                    f"an uncollected task is thrown away. Never tell the "
                    f"user you will report back — report now, or wait."
                ),
                metadata={
                    "task_id": task_id,
                    "background": True,
                    "task": task,
                    "agent_type": agent_type or None,
                },
            )

        result = self._run_task(
            task=task,
            task_context=task_context,
            agent_type=agent_type,
            context=context,
            depth=depth,
        )
        return ToolOutput(text=result.report(), metadata=result.to_dict())

    # ── introspection ────────────────────────────────────────────────────

    def outstanding(self) -> list[dict[str, Any]]:
        """Background tasks still running, for a UI or a run summary."""
        with self._lock:
            return [
                {"task_id": task_id, **self._meta.get(task_id, {})}
                for task_id in self._tasks
            ]
