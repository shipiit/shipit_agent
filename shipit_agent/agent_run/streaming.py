"""Running a turn while watching it: event streams, a live terminal view, narration and SSE.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.runtime import AgentRuntime

# Views ``run_live`` knows how to draw. Anything else is a typo, and used to
# fall through to the default renderer without a word.
_LIVE_STYLES = frozenset({"auto", "rich", "plain", "tree", "modern"})


class StreamingRunMixin:
    """Running a turn while watching it: event streams, a live terminal view, narration and SSE."""

    def run_live(
        self,
        user_prompt: str,
        *,
        file: Any = None,
        style: str = "auto",
        detail: bool = False,
    ) -> str:
        """Run with a live, streaming display and return the answer.

        Tokens print as they're generated (when the LLM adapter streams),
        tool calls appear as ⚙ cards with args, status, and duration, and a
        one-line summary closes the run::

            agent.run_live("Close Q2 and hand me the workbook.")
            # ⚙ build_document(kind="xlsx", …) …
            # ⚙ build_document ✓ 228ms
            #   └ Created XLSX 'Q2 Close' → q2_close.xlsx
            # The workbook is ready — net income formula included.
            # ✔ done · 1 tool call

        Pass ``file=`` to redirect output (any object with ``write``).
        Returns the final answer text; use :meth:`run` when you need the
        full :class:`AgentResult`.

        ``style="tree"`` renders the *shape* of the run instead — every call
        named with its status, decisions marked where they happened. Good for
        debugging and for explaining what an agent did.

        ``style="modern"`` switches to the Narrator — human verbs, collapsed
        work runs, and a tokens/cost footer (see
        ``docs/design/modern-agent-upgrade.md``)::

            agent.run_live("Which accounts are at risk?", style="modern")
            # ⌕ Read 3 files ›
            #   Enterprise Accounts · Open Tickets · Usage by Account
            #
            # Three I would put on your list: …
            #                                    18,240 tokens · $0.12
        """
        if style not in _LIVE_STYLES:
            # A typo used to render the default view silently, which reads as
            # "the style I asked for does nothing".
            raise ValueError(
                f"Unknown style {style!r}. Valid styles: "
                f"{', '.join(sorted(_LIVE_STYLES))}."
            )
        if style == "tree":
            from shipit_agent.narrate import TreeRenderer

            renderer = TreeRenderer(
                file=file, model=getattr(self.llm, "model", None), detail=detail
            )
        elif style == "modern":
            from shipit_agent.narrate import NarratorRenderer

            renderer = NarratorRenderer(
                file=file, model=getattr(self.llm, "model", None)
            )
        else:
            from shipit_agent.observability.activity import StreamRenderer

            renderer = StreamRenderer(file=file, style=style)
        output = ""
        for event in self.stream(user_prompt):
            renderer.feed(event)
            if event.type == "run_completed":
                output = str(event.payload.get("output", "") or "")
        renderer.close()
        return output

    def stream(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
    ):
        """Stream agent events as they happen.

        Same pipeline as :meth:`run`, but yields :class:`AgentEvent` objects
        instead of blocking. This is the low-level feed — every event, in
        order::

            for event in agent.stream("Fix the failing test"):
                if event.type == "text_delta":
                    print(event.payload["chunk"], end="", flush=True)

        ``images`` and ``files`` attach media to the turn, exactly as in
        :meth:`run` — URLs, local paths, or base64 for images; text/markdown/
        code files inlined, PDFs as document blocks::

            for event in agent.stream("What changed?",
                                      images=["diagram.png"], files=["spec.pdf"]):
                ...

        Most callers want one of the three wrappers built on it instead:

        - :meth:`run_live` — the finished transcript, printed for you
        - :meth:`narrate` — the same rows as objects, for your own UI
        - ``shipit_agent.streaming.sse`` — framed for a browser, with each
          event labelled canonical or provisional

        Every event carries ``type``, ``message``, ``payload`` and
        ``timestamp``; see :data:`shipit_agent.models.EventType` for the
        vocabulary.
        """
        user_prompt = self._delegated_prompt(self._expand_slash_command(user_prompt))
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
            )
        )
        user_content = self._user_content_blocks(user_prompt, images, files)
        sources: list[Any] = []
        completed = False
        try:
            with self._run_lock:
                for event in runtime.stream(user_prompt, user_content=user_content):
                    yield event
            completed = True
        finally:
            self._active_runtime = None
            if self.rag is not None:
                sources = self.rag.end_run()
        if completed and sources:
            from shipit_agent.core.models import AgentEvent

            yield AgentEvent(
                type="rag_sources",
                message=f"Captured {len(sources)} RAG source(s)",
                payload={"sources": [s.to_dict() for s in sources]},
            )

    async def astream(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
    ):
        """Feature-complete async counterpart to :meth:`stream`."""
        from shipit_agent.core.async_runtime import AsyncAgentRuntime
        from shipit_agent.core.models import AgentEvent

        async with self._async_run_lock:
            user_prompt = self._delegated_prompt(
                self._expand_slash_command(user_prompt)
            )
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
                )
            )
            user_content = self._user_content_blocks(user_prompt, images, files)
            sources: list[Any] = []
            completed = False
            try:
                async for event in runtime.stream(
                    user_prompt, user_content=user_content
                ):
                    yield event
                completed = True
            finally:
                self._active_runtime = None
                if self.rag is not None:
                    sources = self.rag.end_run()
            if completed and sources:
                yield AgentEvent(
                    type="rag_sources",
                    message=f"Captured {len(sources)} RAG source(s)",
                    payload={"sources": [s.to_dict() for s in sources]},
                )

    def narrate(self, user_prompt: str):
        """Stream *transcript rows* rather than raw events.

        The same collapsing the terminal renderer does — verbs, work runs,
        approvals, sub-agent activity — handed to you as objects so you can
        render them however you like::

            for row in agent.narrate("Which accounts are at risk?"):
                match row:
                    case ProseRow(text):        print(text)
                    case WorkRow(group):        print("·", group.label)
                    case ApprovalRow() as a:    prompt_user(a)

        A row is yielded when it settles — prose closes a work run, and a
        work run closes prose — so you never have to decide when a group is
        finished. Raw events are still there via :meth:`stream` if you need
        them.
        """
        from shipit_agent.narrate.grouping import WorkRunAccumulator

        accumulator = WorkRunAccumulator()
        for event in self.stream(user_prompt):
            for row in accumulator.feed(event):
                yield row
        for row in accumulator.finish():
            yield row

    def stream_sse(self, user_prompt: str):
        """Stream the run as Server-Sent Events, ready for the wire::

            @app.get("/run")
            def run():
                return StreamingResponse(
                    agent.stream_sse(prompt), media_type="text/event-stream"
                )

        Opens with a ``stream_hello`` carrying this process's generation, so a
        reconnecting client knows whether to keep what it already drew, and
        closes with ``[DONE]``. See :mod:`shipit_agent.streaming`.
        """
        from shipit_agent.observability.streaming import hello_frame, sse

        yield sse(hello_frame())
        sequence = 0
        for event in self.stream(user_prompt):
            sequence += 1
            yield sse(event, sequence=sequence)
        yield "event: done\ndata: [DONE]\n\n"
