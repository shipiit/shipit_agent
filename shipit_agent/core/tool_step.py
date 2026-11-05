"""A step where the model called tools: run them as one group, record them and summarise the step.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.core.state import (
    _isolated_tool_state,
    _merge_tool_state,
)
from shipit_agent.core.turn import Turn
from shipit_agent.llms.base import (
    LLMResponse,
)
from shipit_agent.tools import ToolContext


class ToolStepMixin:
    """A step where the model called tools: run them as one group, record them and summarise the step."""

    async def _run_tool_step(
        self,
        turn: Turn,
        *,
        iteration: int,
        response: LLMResponse,
        forced_names: set[str],
    ) -> None:
        """Run the tool calls from one model response as a group, then record them.

        Read-only groups run in parallel; anything that changes state runs in
        order. Emits the group events and the step's observation summary.
        """
        state = turn.state
        registry = turn.registry
        shared_state = turn.shared_state
        tool_runner = turn.tool_runner
        base_prompt = turn.base_prompt
        user_prompt = turn.user_prompt

        tool_call_records = self.assign_tool_call_ids(
            response.tool_calls, state.messages, iteration
        )
        group_output_limit = None
        if (
            self.max_tool_output_chars > 0
            and self.max_tool_output_group_chars > 0
            and response.tool_calls
        ):
            group_output_limit = max(
                1,
                self.max_tool_output_group_chars // len(response.tool_calls),
            )
        state.messages.append(
            Message(
                role="assistant",
                content=response.content,
                tool_calls=list(response.tool_calls),
                metadata={
                    **dict(response.metadata),
                    **(
                        {"reasoning_content": response.reasoning_content}
                        if response.reasoning_content
                        else {}
                    ),
                },
            )
        )
        turn.appended_response_id = id(response)

        group_id = f"tool_group_{iteration}"
        group_result_start = len(state.tool_results)
        self.emit(
            state,
            "tool_group_started",
            "Tool group started",
            group_id=group_id,
            iteration=iteration,
            tool_count=len(tool_call_records),
            tools=[
                {"name": record["name"], "call_id": record["id"]}
                for record in tool_call_records
            ],
        )

        # Only read-only groups fan out — writes keep their order (see
        # runtime.py for the full rationale). Shared decision on
        # RuntimeCore so both loops agree on what is parallel-safe.
        group_is_parallel_safe = all(
            self.read_only_calls(response.tool_calls, registry)
        )
        if (
            self.parallel_tool_execution
            and len(response.tool_calls) > 1
            and group_is_parallel_safe
        ):
            # Run tools concurrently — each on its own isolated copy of
            # shared_state so concurrent writes can't corrupt each other;
            # merged back in original order after all complete.
            isolated_states = [
                _isolated_tool_state(shared_state) for _ in response.tool_calls
            ]
            tasks = []
            semaphore = asyncio.Semaphore(
                self.max_tool_concurrency or len(response.tool_calls)
            )

            async def _bounded_tool_call(**kwargs: Any):
                async with semaphore:
                    return await self._execute_single_tool(**kwargs)

            for idx, tc in enumerate(response.tool_calls):
                context = ToolContext(
                    prompt=user_prompt,
                    system_prompt=base_prompt,
                    metadata=dict(self.metadata),
                    state=isolated_states[idx],
                    session_id=self.session_id,
                )
                tasks.append(
                    _bounded_tool_call(
                        state=state,
                        registry=registry,
                        tool_runner=tool_runner,
                        tool_call=tc,
                        tool_call_record=tool_call_records[idx],
                        context=context,
                        iteration=iteration,
                        model_output_limit=group_output_limit,
                        group_id=group_id,
                    )
                )
            results = await asyncio.gather(*tasks)
            for idx, (tool_result, msg) in enumerate(results):
                _merge_tool_state(shared_state, isolated_states[idx])
                if tool_result is not None:
                    state.tool_results.append(tool_result)
                state.messages.append(msg)
                if tool_result is not None:
                    vision = self.vision_followup(
                        tool_result, response.tool_calls[idx].name
                    )
                    if vision is not None:
                        state.messages.append(vision)

        else:
            for idx, tc in enumerate(response.tool_calls):
                context = ToolContext(
                    prompt=user_prompt,
                    system_prompt=base_prompt,
                    metadata=dict(self.metadata),
                    state=shared_state,
                    session_id=self.session_id,
                )
                tool_result, msg = await self._execute_single_tool(
                    state=state,
                    registry=registry,
                    tool_runner=tool_runner,
                    tool_call=tc,
                    tool_call_record=tool_call_records[idx],
                    context=context,
                    iteration=iteration,
                    model_output_limit=group_output_limit,
                    group_id=group_id,
                )
                if tool_result is not None:
                    state.tool_results.append(tool_result)
                state.messages.append(msg)
                if tool_result is not None:
                    # Mirrors runtime.py: an image-bearing tool result is
                    # bridged into a user-turn image block.
                    vision = self.vision_followup(tool_result, tc.name)
                    if vision is not None:
                        state.messages.append(vision)

        iteration_results = state.tool_results[group_result_start:]
        observation_summary = self._generate_observation_summary(
            tool_results=iteration_results,
            tool_calls=response.tool_calls,
        )
        self.emit(
            state,
            "tool_group_completed",
            "Tool group completed",
            group_id=group_id,
            iteration=iteration,
            tool_count=len(tool_call_records),
            completed_count=len(iteration_results),
            summary=observation_summary,
        )
        if observation_summary:
            state.last_observation = observation_summary
            self.emit(
                state,
                "agent_observation",
                observation_summary,
                summary=observation_summary,
                iteration=iteration,
                next_action="evaluate_results",
                generated_by_model=False,
            )

        self.settle_duplicate_batch(shared_state, state.messages, tool_call_records)
        if state.tool_results:
            shared_state.pop("force_any_tool", None)
        if forced_names:
            remaining_forced = forced_names - {
                result.name for result in state.tool_results
            }
            if remaining_forced:
                shared_state["forced_tool_names"] = remaining_forced
            else:
                shared_state.pop("forced_tool_names", None)
        if (
            self.replan_interval > 0
            and iteration % self.replan_interval == 0
            and iteration < self.max_iterations
        ):
            await self._run_planner_if_needed(
                state=state,
                registry=registry,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
                shared_state=shared_state,
                tool_runner=tool_runner,
            )
