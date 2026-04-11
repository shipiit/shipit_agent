from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Checkpoint:
    """A saved agent state."""

    agent_id: str
    step: int
    state: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)


class PersistentAgent:
    """Agent that can checkpoint and resume across sessions.

    Saves progress periodically so long-running tasks survive
    crashes, timeouts, or user interruptions.

    Example::

        agent = PersistentAgent(
            llm=llm, tools=[...],
            checkpoint_dir="./checkpoints",
            checkpoint_interval=5,
        )
        result = agent.run("Long task", agent_id="task-1")

        # If interrupted, resume:
        result = agent.resume(agent_id="task-1")
    """

    def __init__(
        self,
        *,
        llm: Any,
        tools: list[Any] | None = None,
        checkpoint_dir: str = ".shipit_checkpoints",
        checkpoint_interval: int = 5,
        max_steps: int = 50,
        rag: Any = None,
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.tools = tools or []
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_interval = checkpoint_interval
        self.max_steps = max_steps
        self.rag = rag
        self.agent_kwargs: dict[str, Any] = dict(agent_kwargs)
        if rag is not None:
            self.agent_kwargs["rag"] = rag

    def _checkpoint_path(self, agent_id: str) -> str:
        return os.path.join(self.checkpoint_dir, f"{agent_id}.json")

    def _save_checkpoint(self, checkpoint: Checkpoint) -> None:
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        data = {
            "agent_id": checkpoint.agent_id,
            "step": checkpoint.step,
            "state": checkpoint.state,
            "outputs": checkpoint.outputs,
        }
        with open(self._checkpoint_path(checkpoint.agent_id), "w") as f:
            json.dump(data, f, indent=2)

    def _load_checkpoint(self, agent_id: str) -> Checkpoint | None:
        path = self._checkpoint_path(agent_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        return Checkpoint(
            agent_id=data["agent_id"],
            step=data["step"],
            state=data.get("state", {}),
            outputs=data.get("outputs", []),
        )

    def _delete_checkpoint(self, agent_id: str) -> None:
        path = self._checkpoint_path(agent_id)
        if os.path.exists(path):
            os.remove(path)

    def status(self, agent_id: str) -> dict[str, Any]:
        """Check progress without resuming."""
        checkpoint = self._load_checkpoint(agent_id)
        if checkpoint is None:
            return {"state": "not_found", "agent_id": agent_id}
        return {
            "state": "paused",
            "agent_id": agent_id,
            "steps_done": checkpoint.step,
            "outputs_count": len(checkpoint.outputs),
        }

    def run(self, task: str, *, agent_id: str) -> Any:
        from shipit_agent.agent import Agent

        agent = Agent(llm=self.llm, tools=list(self.tools), **self.agent_kwargs)
        checkpoint = Checkpoint(agent_id=agent_id, step=0, state={"task": task})

        for step in range(1, self.max_steps + 1):
            result = agent.run(f"Step {step} of task: {task}")
            checkpoint.step = step
            checkpoint.outputs.append(result.output)

            if step % self.checkpoint_interval == 0:
                self._save_checkpoint(checkpoint)

            # Check if agent says it's done
            if any(
                w in result.output.lower() for w in ["complete", "finished", "done"]
            ):
                self._delete_checkpoint(agent_id)
                return result

        self._save_checkpoint(checkpoint)
        return Agent(llm=self.llm).run(task)

    def stream(self, task: str, *, agent_id: str = "default"):
        """Stream events from a checkpointed run.

        Yields the inner :class:`Agent` events for every step plus a
        synthetic ``run_completed`` event with the consolidated output.
        Checkpoints are still written every ``checkpoint_interval``
        steps so the run can be resumed if interrupted.
        """
        from shipit_agent.agent import Agent
        from shipit_agent.models import AgentEvent

        agent = Agent(llm=self.llm, tools=list(self.tools), **self.agent_kwargs)
        checkpoint = Checkpoint(agent_id=agent_id, step=0, state={"task": task})

        outputs: list[str] = []
        for step in range(1, self.max_steps + 1):
            yield AgentEvent(
                type="step_started",
                message=f"persistent step {step}/{self.max_steps}",
                payload={"step": step, "agent_id": agent_id},
            )
            step_text = ""
            for event in agent.stream(f"Step {step} of task: {task}"):
                yield event
                if event.type == "run_completed":
                    step_text = event.payload.get("output", "") or step_text
            outputs.append(step_text)
            checkpoint.step = step
            checkpoint.outputs.append(step_text)

            if step % self.checkpoint_interval == 0:
                self._save_checkpoint(checkpoint)

            if any(
                w in (step_text or "").lower() for w in ["complete", "finished", "done"]
            ):
                self._delete_checkpoint(agent_id)
                yield AgentEvent(
                    type="run_completed",
                    message="persistent run completed",
                    payload={"output": step_text, "steps": step, "agent_id": agent_id},
                )
                return

        self._save_checkpoint(checkpoint)
        yield AgentEvent(
            type="run_completed",
            message="persistent run reached max_steps",
            payload={
                "output": outputs[-1] if outputs else "",
                "steps": len(outputs),
                "agent_id": agent_id,
            },
        )

    def resume(self, agent_id: str) -> Any:
        """Resume a checkpointed task."""
        checkpoint = self._load_checkpoint(agent_id)
        if checkpoint is None:
            raise ValueError(f"No checkpoint found for agent_id: {agent_id}")

        task = checkpoint.state.get("task", "")
        from shipit_agent.agent import Agent

        agent = Agent(llm=self.llm, tools=list(self.tools), **self.agent_kwargs)

        for step in range(checkpoint.step + 1, self.max_steps + 1):
            result = agent.run(f"Continue step {step} of task: {task}")
            checkpoint.step = step
            checkpoint.outputs.append(result.output)

            if step % self.checkpoint_interval == 0:
                self._save_checkpoint(checkpoint)

            if any(
                w in result.output.lower() for w in ["complete", "finished", "done"]
            ):
                self._delete_checkpoint(agent_id)
                return result

        self._save_checkpoint(checkpoint)
        return Agent(llm=self.llm).run(task)
