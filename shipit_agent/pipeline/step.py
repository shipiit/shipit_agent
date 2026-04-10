from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class StepResult:
    """Result of a single pipeline step."""

    name: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Step:
    """A single step in a pipeline.

    A step can be backed by an agent, a plain function, or a conditional
    router. Use the ``step()`` helper to create steps conveniently.
    """

    name: str
    agent: Any = None
    fn: Callable[..., str] | None = None
    prompt: str = ""
    router: Callable[..., str] | None = None
    branches: dict[str, "Step"] | None = None
    output_schema: Any = None

    def execute(self, context: dict[str, StepResult], **inputs: Any) -> StepResult:
        """Execute this step, resolving template references from context."""
        if self.router and self.branches:
            branch_key = self.router(context)
            branch_step = self.branches.get(branch_key)
            if branch_step is None:
                return StepResult(name=self.name, output=f"No branch for key: {branch_key}")
            return branch_step.execute(context, **inputs)

        if self.fn is not None:
            # Plain function step
            resolved_prompt = self._resolve_template(self.prompt, context) if self.prompt else ""
            if resolved_prompt:
                result_text = self.fn(resolved_prompt)
            else:
                # Pass context as input text
                input_text = inputs.get("input", "")
                prev = list(context.values())
                if prev:
                    input_text = prev[-1].output
                result_text = self.fn(input_text)
            return StepResult(name=self.name, output=str(result_text))

        if self.agent is not None:
            resolved_prompt = self._resolve_template(self.prompt, context)
            result = self.agent.run(resolved_prompt, output_schema=self.output_schema) if self.output_schema else self.agent.run(resolved_prompt)
            return StepResult(
                name=self.name,
                output=result.output,
                metadata={"parsed": result.parsed} if hasattr(result, "parsed") and result.parsed else {},
            )

        return StepResult(name=self.name, output="No agent or function provided")

    @staticmethod
    def _resolve_template(template: str, context: dict[str, StepResult]) -> str:
        """Replace template references with actual values.

        Supports two forms:
        - ``{step_name.output}`` — access a specific attribute of a step result
        - ``{key}`` — shorthand for ``{key.output}`` (the step's output text)
        """
        # First resolve {step_name.attribute} references
        def dotted_replacer(match: re.Match) -> str:
            step_name = match.group(1)
            attr = match.group(2)
            step_result = context.get(step_name)
            if step_result is None:
                return match.group(0)
            return getattr(step_result, attr, match.group(0))

        result = re.sub(r"\{(\w+)\.(\w+)\}", dotted_replacer, template)

        # Then resolve simple {key} references (shorthand for {key.output})
        def simple_replacer(match: re.Match) -> str:
            key = match.group(1)
            step_result = context.get(key)
            if step_result is None:
                return match.group(0)
            return step_result.output

        result = re.sub(r"\{(\w+)\}", simple_replacer, result)
        return result


@dataclass(slots=True)
class ParallelGroup:
    """A group of steps that run concurrently."""

    steps: list[Step] = field(default_factory=list)

    def execute(self, context: dict[str, StepResult], **inputs: Any) -> list[StepResult]:
        if len(self.steps) <= 1:
            return [s.execute(context, **inputs) for s in self.steps]

        results: dict[int, StepResult] = {}
        with ThreadPoolExecutor(max_workers=len(self.steps)) as pool:
            futures = {
                pool.submit(s.execute, dict(context), **inputs): i
                for i, s in enumerate(self.steps)
            }
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()

        return [results[i] for i in range(len(self.steps))]


def step(
    name: str,
    *,
    agent: Any = None,
    fn: Callable[..., str] | None = None,
    prompt: str = "",
    router: Callable[..., str] | None = None,
    branches: dict[str, Step] | None = None,
    output_schema: Any = None,
) -> Step:
    """Create a pipeline step.

    Example::

        step("research", agent=my_agent, prompt="Find info about {topic}")
        step("clean", fn=str.strip)
        step("route", router=lambda ctx: "a", branches={"a": step_a})
    """
    return Step(
        name=name,
        agent=agent,
        fn=fn,
        prompt=prompt,
        router=router,
        branches=branches,
        output_schema=output_schema,
    )


def parallel(*steps: Step) -> ParallelGroup:
    """Group steps to run concurrently.

    Example::

        parallel(
            step("a", agent=agent_a, prompt="..."),
            step("b", agent=agent_b, prompt="..."),
        )
    """
    return ParallelGroup(steps=list(steps))
