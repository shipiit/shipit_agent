from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.pipeline.step import ParallelGroup, Step, StepResult


@dataclass(slots=True)
class PipelineResult:
    """Result of a pipeline run."""

    output: str
    steps: dict[str, StepResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "steps": {
                k: {"name": v.name, "output": v.output} for k, v in self.steps.items()
            },
        }


class Pipeline:
    """Deterministic composition of agents and functions.

    Example::

        pipe = Pipeline.sequential(
            step("research", agent=researcher, prompt="Find {topic}"),
            step("write", agent=writer, prompt="Write about: {research.output}"),
        )
        result = pipe.run(topic="AI")
        result.output                  # final step output
        result.steps["research"].output  # intermediate result

    Supports sequential steps, parallel groups, conditional routing,
    and plain Python functions.
    """

    def __init__(self, *stages: Step | ParallelGroup) -> None:
        self.stages: list[Step | ParallelGroup] = list(stages)

    @classmethod
    def sequential(cls, *steps: Step) -> "Pipeline":
        """Create a pipeline that runs steps one after another."""
        return cls(*steps)

    def run(self, **inputs: Any) -> PipelineResult:
        """Execute the pipeline.

        Keyword arguments are injected into the first step's prompt template
        via ``{key}`` substitution.
        """
        context: dict[str, StepResult] = {}

        # Inject raw inputs as pseudo-steps so templates can reference them
        for key, value in inputs.items():
            context[key] = StepResult(name=key, output=str(value))

        last_output = ""

        for stage in self.stages:
            if isinstance(stage, ParallelGroup):
                results = stage.execute(context, **inputs)
                for r in results:
                    context[r.name] = r
                    last_output = r.output
            elif isinstance(stage, Step):
                result = stage.execute(context, **inputs)
                context[result.name] = result
                last_output = result.output
            else:
                raise TypeError(f"Unknown stage type: {type(stage)}")

        return PipelineResult(
            output=last_output,
            steps={k: v for k, v in context.items() if k not in inputs},
        )

    def stream(self, **inputs: Any):
        """Execute the pipeline and yield events for each step.

        Example::

            for event in pipe.stream(topic="AI"):
                print(f"[{event.type}] {event.message}")
        """
        from shipit_agent.models import AgentEvent

        context: dict[str, StepResult] = {}
        for key, value in inputs.items():
            context[key] = StepResult(name=key, output=str(value))

        yield AgentEvent(
            type="run_started",
            message=f"Pipeline started ({len(self.stages)} stages)",
            payload={"stages": len(self.stages), "inputs": list(inputs.keys())},
        )

        last_output = ""

        for stage_idx, stage in enumerate(self.stages, 1):
            if isinstance(stage, ParallelGroup):
                names = [s.name for s in stage.steps]
                yield AgentEvent(
                    type="step_started",
                    message=f"Parallel stage {stage_idx}: {names}",
                    payload={"parallel": True, "steps": names},
                )
                results = stage.execute(context, **inputs)
                for r in results:
                    context[r.name] = r
                    last_output = r.output
                    yield AgentEvent(
                        type="tool_completed",
                        message=f"Step '{r.name}' completed",
                        payload={"step": r.name, "output": r.output[:200]},
                    )

            elif isinstance(stage, Step):
                yield AgentEvent(
                    type="step_started",
                    message=f"Step '{stage.name}' started",
                    payload={"step": stage.name},
                )

                # If the step has an agent, stream inner agent events
                if stage.agent is not None:
                    resolved_prompt = stage._resolve_template(stage.prompt, context)
                    for event in stage.agent.stream(resolved_prompt):
                        event.payload["pipeline_step"] = stage.name
                        yield event

                result = stage.execute(context, **inputs)
                context[result.name] = result
                last_output = result.output
                yield AgentEvent(
                    type="tool_completed",
                    message=f"Step '{stage.name}' completed",
                    payload={"step": stage.name, "output": result.output[:200]},
                )

        yield AgentEvent(
            type="run_completed",
            message="Pipeline completed",
            payload={"output": last_output[:300], "steps_completed": len(self.stages)},
        )
