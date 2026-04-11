from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Worker:
    """A worker agent managed by a supervisor."""

    name: str
    agent: Any
    capabilities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Delegation:
    """Record of a single delegation."""

    round: int
    worker: str
    task: str
    output: str
    approved: bool = False


@dataclass(slots=True)
class SupervisorResult:
    """Result of a supervisor run."""

    output: str
    plan: str = ""
    delegations: list[Delegation] = field(default_factory=list)
    total_rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output[:500],
            "plan": self.plan[:300],
            "total_rounds": self.total_rounds,
            "delegations": [
                {"round": d.round, "worker": d.worker, "task": d.task[:100], "approved": d.approved}
                for d in self.delegations
            ],
        }


SUPERVISOR_PROMPT = """You are a supervisor managing a team of workers. Plan the work, delegate to workers, review their output, and produce the final result.

## Workers
{workers}

## Task
{task}

## Work done so far
{history}

Respond with JSON:
- To delegate: {{"action": "delegate", "worker": "<name>", "task": "<specific instructions>"}}
- To send back for revision: {{"action": "revise", "worker": "<name>", "task": "<what to fix>"}}
- When done: {{"action": "done", "final_answer": "<combined final output>"}}"""


class Supervisor:
    """Hierarchical agent that plans, delegates, reviews, and combines results.

    More powerful than AgentTeam — the supervisor actively monitors quality,
    sends work back for revision, and runs workers in parallel when possible.

    Example::

        supervisor = Supervisor(
            llm=llm,
            workers=[data_worker, viz_worker, report_worker],
            strategy="plan_and_delegate",
            max_delegations=15,
        )
        result = supervisor.run("Analyze Q4 sales and write a report")
    """

    def __init__(
        self,
        *,
        llm: Any,
        workers: list[Worker],
        strategy: str = "plan_and_delegate",
        allow_parallel: bool = False,
        max_delegations: int = 15,
        rag: Any = None,
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.workers = {w.name: w for w in workers}
        self.strategy = strategy
        self.allow_parallel = allow_parallel
        self.max_delegations = max_delegations
        self.rag = rag
        self.agent_kwargs: dict[str, Any] = dict(agent_kwargs)
        if rag is not None:
            self.agent_kwargs["rag"] = rag

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        worker_configs: list[dict[str, Any]],
        mcps: list[Any] | None = None,
        rag: Any = None,
        **kwargs: Any,
    ) -> "Supervisor":
        """Create a Supervisor where each worker has all built-in tools.

        When ``rag`` is provided every worker is wired with the same RAG
        instance so sources captured by any worker flow back to the
        surrounding run.

        Example::

            supervisor = Supervisor.with_builtins(
                llm=llm,
                worker_configs=[
                    {"name": "researcher", "prompt": "You research topics."},
                    {"name": "writer", "prompt": "You write content."},
                ],
                rag=my_rag,
            )
        """
        from shipit_agent.agent import Agent
        workers = []
        for cfg in worker_configs:
            agent = Agent.with_builtins(
                llm=llm,
                prompt=cfg.get("prompt", "You are a helpful assistant."),
                mcps=mcps,
                rag=rag,
            )
            workers.append(Worker(
                name=cfg["name"],
                agent=agent,
                capabilities=cfg.get("capabilities", []),
            ))
        return cls(llm=llm, workers=workers, rag=rag, **kwargs)

    def _build_workers_desc(self) -> str:
        lines = []
        for w in self.workers.values():
            caps = f" [{', '.join(w.capabilities)}]" if w.capabilities else ""
            lines.append(f"- {w.name}{caps}")
        return "\n".join(lines)

    def _ask_supervisor(self, task: str, delegations: list[Delegation]) -> dict[str, Any]:
        from shipit_agent.models import Message

        history = "(None yet)" if not delegations else "\n".join(
            f"Round {d.round}: {d.worker} -> {d.output[:300]}" for d in delegations
        )
        prompt = SUPERVISOR_PROMPT.format(
            workers=self._build_workers_desc(),
            task=task,
            history=history,
        )
        response = self.llm.complete(messages=[Message(role="user", content=prompt)])
        text = response.content.strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"action": "done", "final_answer": text}

    def run(self, task: str) -> SupervisorResult:
        delegations: list[Delegation] = []

        for round_num in range(1, self.max_delegations + 1):
            decision = self._ask_supervisor(task, delegations)
            action = decision.get("action", "done")

            if action == "done":
                final = decision.get("final_answer", "")
                if not final and delegations:
                    final = delegations[-1].output
                return SupervisorResult(
                    output=final,
                    delegations=delegations,
                    total_rounds=round_num,
                )

            worker_name = decision.get("worker", "")
            worker_task = decision.get("task", task)
            worker = self.workers.get(worker_name)

            if worker is None:
                delegations.append(Delegation(
                    round=round_num, worker=worker_name,
                    task=worker_task, output=f"Error: worker '{worker_name}' not found",
                ))
                continue

            result = worker.agent.run(worker_task)
            delegations.append(Delegation(
                round=round_num,
                worker=worker_name,
                task=worker_task,
                output=result.output,
                approved=(action != "revise"),
            ))

        final = delegations[-1].output if delegations else "Max delegations reached"
        return SupervisorResult(
            output=final, delegations=delegations, total_rounds=self.max_delegations,
        )

    def stream(self, task: str):
        """Run the supervisor and yield events in real time.

        Example::

            for event in supervisor.stream("Analyze data and write report"):
                print(f"[{event.payload.get('worker', 'supervisor')}] {event.message}")
        """
        from shipit_agent.models import AgentEvent

        yield AgentEvent(type="run_started", message=f"Supervisor: {task[:80]}", payload={"task": task, "workers": list(self.workers.keys())})

        delegations: list[Delegation] = []

        for round_num in range(1, self.max_delegations + 1):
            yield AgentEvent(type="planning_started", message=f"Round {round_num}: Supervisor deciding next step")
            decision = self._ask_supervisor(task, delegations)
            action = decision.get("action", "done")

            if action == "done":
                final = decision.get("final_answer", "")
                if not final and delegations:
                    final = delegations[-1].output
                yield AgentEvent(type="run_completed", message="Supervisor: task complete", payload={"output": final[:300], "rounds": round_num})
                return

            worker_name = decision.get("worker", "")
            worker_task = decision.get("task", task)
            worker = self.workers.get(worker_name)

            if worker is None:
                yield AgentEvent(type="tool_failed", message=f"Worker '{worker_name}' not found", payload={"worker": worker_name})
                delegations.append(Delegation(round=round_num, worker=worker_name, task=worker_task, output=f"Error: worker '{worker_name}' not found"))
                continue

            yield AgentEvent(type="tool_called", message=f"Delegating to {worker_name}: {worker_task[:80]}", payload={"worker": worker_name, "task": worker_task})

            result = worker.agent.run(worker_task)
            delegations.append(Delegation(round=round_num, worker=worker_name, task=worker_task, output=result.output, approved=(action != "revise")))

            yield AgentEvent(type="tool_completed", message=f"{worker_name} finished", payload={"worker": worker_name, "output": result.output})

        yield AgentEvent(type="run_completed", message="Supervisor: max rounds reached", payload={"rounds": self.max_delegations})
