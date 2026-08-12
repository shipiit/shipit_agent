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
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from shipit_agent.llms.base import LLM
from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import SUB_AGENT_SYSTEM_PROMPT

__all__ = [
    "SubAgentTool",
    "SubAgentResult",
    "PARENT_STATE_KEY",
    "DEPTH_STATE_KEY",
    "EVENT_SINK_KEY",
]

# The runtime publishes the parent's tools and control plane here so a child
# can be built that is strictly no more capable.
PARENT_STATE_KEY = "subagent_parent"
# The runtime publishes an event sink here so a child's work is visible in
# the parent's transcript instead of vanishing into a black box.
EVENT_SINK_KEY = "subagent_event_sink"
DEPTH_STATE_KEY = "subagent_depth"

# How deep delegation may go. Without a cap, a model that likes delegating
# spawns a subagent that spawns a subagent, and the run never terminates.
MAX_DEPTH = 2


# A subagent that hasn't finished in this many turns is not going to.
DEFAULT_MAX_ITERATIONS = 12

# Tools a subagent never gets, regardless of what the parent holds.
_NEVER_INHERITED = frozenset({
    # Recursion is capped by depth, but a subagent asking the *human* a
    # question is worse: the parent is mid-turn and nobody is watching the
    # child's stdout.
    "ask_user",
    "ask_user_async",
    "human_review",
})


def _state(context: Any, attribute: str) -> dict[str, Any]:
    """Read a mapping off the context, tolerating duck-typed stand-ins.

    Tools are handed a real ``ToolContext``, but embedders and tests pass
    lighter objects; a missing attribute should not be the difference between
    delegating and raising.
    """
    value = getattr(context, attribute, None)
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class SubAgentResult:
    """What a delegated task produced."""

    task: str
    output: str
    agent_type: str | None = None
    iterations: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    gave_up: bool = False
    give_up_reason: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.gave_up

    def report(self) -> str:
        """What the parent sees — the answer, plus why if it failed."""
        if self.error:
            return f"Sub-agent failed: {self.error}"
        if self.gave_up:
            return (
                f"Sub-agent could not complete the task: {self.give_up_reason}"
            )
        return self.output or "(the sub-agent produced no output)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "agent_type": self.agent_type,
            "ok": self.ok,
            "iterations": self.iterations,
            # NOT "tool_calls": the runtime reserves that key on message
            # metadata for the assistant's tool-call *records*, and a tool
            # result's metadata is merged onto its message. An int there makes
            # the LiteLLM serializer iterate an integer.
            "tool_call_count": self.tool_calls,
            "usage": dict(self.usage),
            "gave_up": self.gave_up,
            "error": self.error,
            # Retained from the original tool's contract.
            "delegated": True,
        }


class SubAgentTool:
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
    ) -> None:
        self.llm = llm
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
        self._task_ids = count(1)
        self._lock = threading.Lock()

    def close(self) -> None:
        """Release the thread pool, cancelling anything still queued."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:  # best-effort; GC order is not guaranteed
        try:
            self.close()
        except Exception:
            pass

    def _result_with_timeout(self, future: Future[SubAgentResult]) -> SubAgentResult:
        """``future.result()`` bounded by ``self.timeout``.

        On expiry the future is cancelled and a failed ``SubAgentResult`` is
        returned rather than raised, so one slow child degrades to a reported
        failure the parent can reason about instead of hanging the run.
        """
        try:
            return future.result(timeout=self.timeout)
        except FuturesTimeout:
            future.cancel()
            return SubAgentResult(
                task="",
                output=(
                    f"Sub-agent exceeded its {self.timeout:.0f}s time limit "
                    "and was abandoned."
                ),
                error="timeout",
            )

    # ── schema ───────────────────────────────────────────────────────────

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": (
                                "The task, stated so someone with no other "
                                "context could do it. Say what to return."
                            ),
                        },
                        # NOT named "context": ToolRunner strips `context`
                        # and `self` from tool arguments because they collide
                        # with the positional ToolContext. The original tool
                        # used that name, so the model's supporting context
                        # was silently dropped before the tool ever saw it.
                        "details": {
                            "type": "string",
                            "description": (
                                "Facts the sub-agent needs — paths, ids, "
                                "constraints. It cannot see your conversation."
                            ),
                        },
                        "agent_type": {
                            "type": "string",
                            "description": (
                                "A specialist role, e.g. 'researcher', "
                                "'code-reviewer'. Omit for general-purpose."
                            ),
                        },
                        "background": {
                            "type": "boolean",
                            "description": (
                                "Start it and return a task id immediately so "
                                "you can keep working."
                            ),
                            "default": False,
                        },
                        "collect": {
                            "type": "string",
                            "description": (
                                "A task id from a background call — waits for "
                                "and returns that task's result. Pass 'all' to "
                                "collect every outstanding task. When "
                                "collecting, `task` is ignored, so repeat the "
                                "original task text there."
                            ),
                        },
                    },
                    # `task` is required even though a collect call does not
                    # use it. An all-optional schema tells a weaker model that
                    # nothing is needed, and it sends `{}` — observed live with
                    # Gemma 4, which called the tool with no arguments at all.
                    "required": ["task"],
                },
            },
        }

    # ── building the child ───────────────────────────────────────────────

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

    def _build_agent(
        self, context: ToolContext, agent_type: str, depth: int
    ) -> Any:
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
    ) -> SubAgentResult:
        result = SubAgentResult(task=task, output="", agent_type=agent_type or None)
        label = agent_type or "sub-agent"
        sink = _state(context, "state").get(EVENT_SINK_KEY)

        try:
            agent = self._build_agent(context, agent_type, depth)
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
            return result

        result.output = output or ""
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
        from shipit_agent.models import AgentResult

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

    def _collect(self, collect: str) -> ToolOutput:
        if collect.lower() == "all":
            return self._collect_all()

        with self._lock:
            future = self._tasks.get(collect)
            known = ", ".join(sorted(self._tasks)) or "none"
        if future is None:
            return ToolOutput(
                text=f"No background task '{collect}'. Outstanding: {known}.",
                metadata={"ok": False, "collect": collect},
            )
        try:
            result = self._result_with_timeout(future)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._tasks.pop(collect, None)
                self._meta.pop(collect, None)
            return ToolOutput(
                text=f"Background task '{collect}' failed: {exc}",
                metadata={"ok": False, "collect": collect, "error": str(exc)},
            )
        with self._lock:
            self._tasks.pop(collect, None)
            self._meta.pop(collect, None)
        return ToolOutput(
            text=result.report(),
            metadata={**result.to_dict(), "collect": collect, "background": True},
        )

    def _collect_all(self) -> ToolOutput:
        """Wait for every outstanding task and return one combined report."""
        with self._lock:
            outstanding = list(self._tasks.items())
        if not outstanding:
            return ToolOutput(
                text="No background tasks are outstanding.",
                metadata={"ok": True, "collected": 0},
            )

        sections: list[str] = []
        results: list[dict[str, Any]] = []
        for task_id, future in outstanding:
            try:
                result = self._result_with_timeout(future)
                sections.append(f"## {task_id}: {result.task}\n{result.report()}")
                results.append(result.to_dict())
            except Exception as exc:  # noqa: BLE001
                sections.append(f"## {task_id}\nFailed: {exc}")
                results.append({"task_id": task_id, "ok": False, "error": str(exc)})
            with self._lock:
                self._tasks.pop(task_id, None)
                self._meta.pop(task_id, None)

        return ToolOutput(
            text="\n\n".join(sections),
            metadata={"collected": len(results), "results": results},
        )

    # ── introspection ────────────────────────────────────────────────────

    def outstanding(self) -> list[dict[str, Any]]:
        """Background tasks still running, for a UI or a run summary."""
        with self._lock:
            return [
                {"task_id": task_id, **self._meta.get(task_id, {})}
                for task_id in self._tasks
            ]
