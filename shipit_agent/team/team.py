from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.team.agent import TeamAgent


@dataclass(slots=True)
class TeamRound:
    """Record of one round of team coordination."""

    number: int
    agent: str
    prompt: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TeamResult:
    """Result of a team run."""

    output: str
    rounds: list[TeamRound] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "rounds": [
                {
                    "number": r.number,
                    "agent": r.agent,
                    "prompt": r.prompt[:100],
                    "output": r.output[:200],
                }
                for r in self.rounds
            ],
        }


COORDINATOR_PROMPT = """You are a team coordinator. Your job is to route tasks to the right team member and combine their outputs into a final answer.

## Team Members
{agent_descriptions}

## Rules
1. Respond with JSON: {{"next_agent": "<name>", "prompt": "<what to tell them>", "done": false}}
2. When the task is complete, respond: {{"next_agent": null, "prompt": null, "done": true, "final_answer": "<the answer>"}}
3. Review each agent's output before deciding next steps
4. You can send work back to an agent for revision

## Task
{task}

## Conversation So Far
{history}

Respond with JSON only."""


class AgentTeam:
    """Multi-agent team with LLM-routed coordination.

    The coordinator LLM decides which agent should work next based on
    the task and conversation history. No manual graph wiring needed.

    Example::

        team = AgentTeam(
            name="research-team",
            coordinator=llm,
            agents=[researcher, writer, reviewer],
            max_rounds=10,
        )
        result = team.run("Write a guide about async Python")

        for round in result.rounds:
            print(f"Round {round.number}: {round.agent}")
    """

    def __init__(
        self,
        *,
        name: str = "team",
        coordinator: Any,
        agents: list[TeamAgent],
        max_rounds: int = 10,
        shared_memory: bool = False,
    ) -> None:
        self.name = name
        self.coordinator = coordinator
        self.agents = {a.name: a for a in agents}
        self.max_rounds = max_rounds
        self.shared_memory = shared_memory

    def _build_agent_descriptions(self) -> str:
        lines = []
        for a in self.agents.values():
            caps = (
                f" (capabilities: {', '.join(a.capabilities)})"
                if a.capabilities
                else ""
            )
            lines.append(f"- **{a.name}**: {a.role}{caps}")
        return "\n".join(lines)

    def _build_history(self, rounds: list[TeamRound]) -> str:
        if not rounds:
            return "(No conversation yet)"
        lines = []
        for r in rounds:
            lines.append(f"[Round {r.number}] {r.agent}: {r.output[:500]}")
        return "\n".join(lines)

    def _ask_coordinator(self, task: str, rounds: list[TeamRound]) -> dict[str, Any]:
        from shipit_agent.models import Message

        prompt = COORDINATOR_PROMPT.format(
            agent_descriptions=self._build_agent_descriptions(),
            task=task,
            history=self._build_history(rounds),
        )
        response = self.coordinator.complete(
            messages=[Message(role="user", content=prompt)],
        )
        text = response.content.strip()
        # Extract JSON from response
        try:
            # Try to find JSON in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"done": True, "final_answer": text, "next_agent": None, "prompt": None}

    def run(self, task: str) -> TeamResult:
        rounds: list[TeamRound] = []

        for round_num in range(1, self.max_rounds + 1):
            decision = self._ask_coordinator(task, rounds)

            if decision.get("done"):
                final = decision.get("final_answer", "")
                if not final and rounds:
                    final = rounds[-1].output
                return TeamResult(output=final, rounds=rounds)

            agent_name = decision.get("next_agent", "")
            agent_prompt = decision.get("prompt", task)
            agent = self.agents.get(agent_name)

            if agent is None:
                rounds.append(
                    TeamRound(
                        number=round_num,
                        agent=agent_name or "unknown",
                        prompt=agent_prompt,
                        output=f"Error: agent '{agent_name}' not found in team",
                    )
                )
                continue

            result = agent.agent.run(agent_prompt)
            rounds.append(
                TeamRound(
                    number=round_num,
                    agent=agent_name,
                    prompt=agent_prompt,
                    output=result.output,
                )
            )

        # Max rounds reached — return last output
        final = rounds[-1].output if rounds else "Max rounds reached with no output"
        return TeamResult(output=final, rounds=rounds)

    def stream(self, task: str):
        """Run the team and yield events in real time.

        Yields AgentEvent objects as the coordinator delegates work,
        workers execute, and the team converges on a result. Inner
        agent events are forwarded with the worker name tagged.

        Example::

            for event in team.stream("Write a guide"):
                print(f"[{event.payload.get('agent', 'coordinator')}] {event.message}")
        """
        from shipit_agent.models import AgentEvent

        yield AgentEvent(
            type="run_started",
            message=f"Team '{self.name}' started",
            payload={"task": task, "agents": list(self.agents.keys())},
        )

        rounds: list[TeamRound] = []

        for round_num in range(1, self.max_rounds + 1):
            yield AgentEvent(
                type="planning_started",
                message=f"Round {round_num}: Coordinator deciding next step",
                payload={"round": round_num},
            )

            decision = self._ask_coordinator(task, rounds)

            if decision.get("done"):
                final = decision.get("final_answer", "")
                if not final and rounds:
                    final = rounds[-1].output
                yield AgentEvent(
                    type="run_completed",
                    message="Team completed",
                    payload={"output": final[:300], "rounds": round_num},
                )
                return

            agent_name = decision.get("next_agent", "")
            agent_prompt = decision.get("prompt", task)
            agent = self.agents.get(agent_name)

            if agent is None:
                yield AgentEvent(
                    type="tool_failed",
                    message=f"Agent '{agent_name}' not found",
                    payload={"agent": agent_name},
                )
                rounds.append(
                    TeamRound(
                        number=round_num,
                        agent=agent_name or "unknown",
                        prompt=agent_prompt,
                        output=f"Error: agent '{agent_name}' not found",
                    )
                )
                continue

            yield AgentEvent(
                type="tool_called",
                message=f"Delegating to {agent_name}: {agent_prompt[:80]}",
                payload={"agent": agent_name, "prompt": agent_prompt},
            )

            result = agent.agent.run(agent_prompt)
            rounds.append(
                TeamRound(
                    number=round_num,
                    agent=agent_name,
                    prompt=agent_prompt,
                    output=result.output,
                )
            )

            yield AgentEvent(
                type="tool_completed",
                message=f"{agent_name} finished",
                payload={"agent": agent_name, "output": result.output},
            )

        yield AgentEvent(
            type="run_completed",
            message="Team max rounds reached",
            payload={"rounds": self.max_rounds},
        )
