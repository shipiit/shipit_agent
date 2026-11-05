"""Running a turn to completion: ``run`` from synchronous code, ``run_async`` / ``arun`` from async code.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from shipit_agent.core.models import AgentResult
from shipit_agent.core.runtime import AgentRuntime

# Moved methods log under the agent's own name, so filters and levels
# configured for it keep applying.
logger = logging.getLogger("shipit_agent.agent")


class BlockingRunMixin:
    """Running a turn to completion: ``run`` from synchronous code, ``run_async`` / ``arun`` from async code."""

    def run(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
        output_schema: Any = None,
        max_validation_retries: int = 2,
    ) -> AgentResult:
        """Execute the agent loop and return the final result.

        ``images`` attaches pictures to this turn — each entry may be an
        ``http(s)`` URL, a local file path, or a base64/data: payload
        (needs a vision-capable model). ``files`` attaches documents: text,
        markdown and code files are inlined (portable to every provider);
        PDFs ride as native document blocks where the provider reads PDF.
        With ``Agent(media_parser=...)`` set, inline references in the
        prompt (``[https://…/x.png]``, ``![alt](url)``) attach automatically.

        Steps:
        1. Optionally append structured output schema instructions.
        2. Compute selected skills once — reused for prompt, tools, metadata.
        3. Build the ``AgentRuntime`` with effective prompt, tools, and
           boosted iteration budget.
        4. Run the loop: LLM call → tool execution → repeat.
        5. Optionally parse the output against ``output_schema``.
        6. Return ``AgentResult`` with output, messages, events, and metadata.
        """
        user_prompt = self._delegated_prompt(self._expand_slash_command(user_prompt))
        # Append schema instructions to the USER prompt (not system prompt)
        # so the model can still use tools normally and only formats the
        # final answer as JSON. Bedrock returns empty content when schema
        # instructions pollute the system prompt.
        effective_user_prompt = user_prompt
        response_format: dict[str, Any] | None = None
        if output_schema:
            from shipit_agent.core.structured import (
                build_schema_prompt,
                schema_to_response_format,
            )

            effective_user_prompt = user_prompt + build_schema_prompt(output_schema)
            # Native response_format is applied by the runtime only on the
            # tool-less final turn; the prompt instruction above still drives
            # the format on providers/mid-loop, and validate_with_retry below
            # remains the safety net.
            response_format = schema_to_response_format(output_schema) or None

        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(
            user_prompt, selected_skills=selected_skills
        )
        skill_ids, skill_tool_names, skill_details = self._runtime_skill_metadata(
            selected_skills
        )

        runtime = self._active_runtime = AgentRuntime(
            **self._runtime_options(
                user_prompt=user_prompt,
                selected_skills=selected_skills,
                effective_tools=effective_tools,
                skill_ids=skill_ids,
                skill_tool_names=skill_tool_names,
                skill_details=skill_details,
                response_format=response_format,
            )
        )
        try:
            with self._run_lock:
                state, response = runtime.run(
                    effective_user_prompt,
                    user_content=self._user_content_blocks(
                        effective_user_prompt, images, files
                    ),
                )
        finally:
            self._active_runtime = None

        # Optionally parse structured output from the LLM response, with
        # validation-retry: if the first parse fails, send the error back
        # to the same LLM (no tools) and ask for a corrected response.
        # Cheap fix-it round trip; only fires when the first parse fails.
        parsed = None
        if output_schema and response.content:
            from shipit_agent.core.structured_output import validate_with_retry

            parsed, retry_text, attempts, attempt_log = validate_with_retry(
                llm=self.llm,
                raw_text=response.content,
                schema=output_schema,
                history=state.messages,
                max_retries=max_validation_retries,
            )
            if parsed is None:
                logger.warning(
                    "output_schema parsing failed after %d attempts. Last error: %s — raw: %s",
                    attempts,
                    attempt_log[-1]["error"] if attempt_log else "unknown",
                    response.content[:500],
                )
            elif attempts > 1:
                # Retry succeeded — surface the corrected text as the output.
                logger.info(
                    "output_schema parsed on attempt %d (after %d failures)",
                    attempts,
                    attempts - 1,
                )
                response.content = retry_text
        elif output_schema and not response.content:
            logger.warning(
                "output_schema was set but LLM returned empty content — "
                "parsed will be None. Try increasing max_iterations."
            )

        rag_sources = self.rag.end_run() if self.rag is not None else []

        # Attach skill metadata so callers can see what was used.
        result_metadata = dict(response.metadata)
        for key in ("gave_up", "give_up_reason", "give_up_needs"):
            if key in runtime.metadata:
                result_metadata[key] = runtime.metadata[key]
        result_metadata["used_skills"] = skill_ids
        result_metadata["used_skill_tools"] = skill_tool_names
        result_metadata["usage"] = dict(runtime._total_usage)
        result_metadata["run_summary"] = runtime._build_run_summary(state)

        return AgentResult(
            output=response.content,
            messages=state.messages,
            events=state.events,
            tool_results=state.tool_results,
            metadata=result_metadata,
            parsed=parsed,
            rag_sources=rag_sources,
        )

    async def run_async(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
        output_schema: Any = None,
        max_validation_retries: int = 2,
    ) -> AgentResult:
        """Async equivalent of :meth:`run` using the complete Agent pipeline."""
        from shipit_agent.core.async_runtime import AsyncAgentRuntime

        async with self._async_run_lock:
            user_prompt = self._delegated_prompt(
                self._expand_slash_command(user_prompt)
            )
            effective_user_prompt = user_prompt
            response_format: dict[str, Any] | None = None
            if output_schema:
                from shipit_agent.core.structured import (
                    build_schema_prompt,
                    schema_to_response_format,
                )

                effective_user_prompt = user_prompt + build_schema_prompt(output_schema)
                response_format = schema_to_response_format(output_schema) or None

            if self.rag is not None:
                self.rag.begin_run()
            selected_skills = self._selected_skills(user_prompt)
            effective_tools = self._effective_tools(
                user_prompt, selected_skills=selected_skills
            )
            skill_ids, skill_tool_names, skill_details = self._runtime_skill_metadata(
                selected_skills
            )
            runtime = self._active_runtime = AsyncAgentRuntime(
                **self._runtime_options(
                    user_prompt=user_prompt,
                    selected_skills=selected_skills,
                    effective_tools=effective_tools,
                    skill_ids=skill_ids,
                    skill_tool_names=skill_tool_names,
                    skill_details=skill_details,
                    response_format=response_format,
                )
            )
            try:
                state, response = await runtime.run(
                    effective_user_prompt,
                    user_content=self._user_content_blocks(
                        effective_user_prompt, images, files
                    ),
                )
            finally:
                self._active_runtime = None

            parsed = None
            if output_schema and response.content:
                from shipit_agent.core.structured_output import validate_with_retry

                parsed, retry_text, attempts, attempt_log = await asyncio.to_thread(
                    validate_with_retry,
                    llm=self.llm,
                    raw_text=response.content,
                    schema=output_schema,
                    history=state.messages,
                    max_retries=max_validation_retries,
                )
                if parsed is None:
                    logger.warning(
                        "output_schema parsing failed after %d attempts. Last error: %s",
                        attempts,
                        attempt_log[-1]["error"] if attempt_log else "unknown",
                    )
                elif attempts > 1:
                    response.content = retry_text

            rag_sources = self.rag.end_run() if self.rag is not None else []
            result_metadata = dict(response.metadata)
            for key in ("gave_up", "give_up_reason", "give_up_needs"):
                if key in runtime.metadata:
                    result_metadata[key] = runtime.metadata[key]
            result_metadata["used_skills"] = skill_ids
            result_metadata["used_skill_tools"] = skill_tool_names
            result_metadata["usage"] = dict(runtime._total_usage)
            result_metadata["run_summary"] = runtime._build_run_summary(state)
            return AgentResult(
                output=response.content,
                messages=state.messages,
                events=state.events,
                tool_results=state.tool_results,
                metadata=result_metadata,
                parsed=parsed,
                rag_sources=rag_sources,
            )

    async def arun(self, user_prompt: str, **kwargs: Any) -> AgentResult:
        """Concise alias for :meth:`run_async`."""
        return await self.run_async(user_prompt, **kwargs)
