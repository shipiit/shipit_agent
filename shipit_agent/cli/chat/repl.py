"""ChatREPL: the chat loop and one turn of it; the rest comes from its mixins."""

from __future__ import annotations

import sys
import uuid
from typing import Any

from shipit_agent.stores import InMemorySessionStore

from .agents import agent_chat_session, make_agent, stream_any_agent
from .providers import current_model_name, current_provider_name
from .repl_commands import CommandsMixin
from .repl_input import InputMixin
from .repl_state import StateMixin
from .repl_views import ViewsMixin
from .style import bold, cyan, dim, green, magenta, red, typewriter


class ChatREPL(InputMixin, CommandsMixin, ViewsMixin, StateMixin):
    """Modern multi-agent chat REPL."""

    render_style: str = "compact"

    SLASH_COMMANDS = (
        "/help",
        "/style",
        "/agent",
        "/agents",
        "/tools",
        "/sources",
        "/index",
        "/rag",
        "/goal",
        "/reflect",
        "/verify",
        "/history",
        "/clear",
        "/save",
        "/load",
        "/reset",
        "/quiet",
        "/stream",
        "/provider",
        "/model",
        "/info",
        "/exit",
        "/quit",
    )

    def __init__(
        self,
        *,
        llm: Any,
        agent_type: str = "deep",
        provider: str | None = None,
        rag: Any = None,
        workspace_root: str = ".shipit_workspace",
        use_builtins: bool = True,
        session_id: str | None = None,
        session_store: Any = None,
        quiet: bool = False,
        reflect: bool = False,
        verify: bool = False,
        typewriter_enabled: bool = True,
    ) -> None:
        self.llm = llm
        self.agent_type = agent_type
        self.provider = current_provider_name(provider)
        self.rag = rag
        self.workspace_root = workspace_root
        self.use_builtins = use_builtins
        self.session_id = session_id or f"chat-{uuid.uuid4().hex[:8]}"
        self.session_store = session_store or InMemorySessionStore()
        self.quiet = quiet
        self.reflect = reflect
        self.verify = verify
        self.typewriter_enabled = typewriter_enabled
        self.last_sources: list[Any] = []
        self.goal_objective: str | None = None
        self.goal_criteria: list[str] | None = None
        # Tools the user approved with [a]lways for this session.
        self.always_allowed: set[str] = set()

        self.agent = self._make_agent()
        self._wire_permission_prompt()
        self.chat = agent_chat_session(
            self.agent,
            session_id=self.session_id,
            session_store=self.session_store,
        )

    # ---- public entry points -------------------------------------------

    def run(self, *, input_fn=input, output=print) -> int:
        from shipit_agent.cli.tui import BottomInputTerminal

        self._install_readline()
        # Claude-Code layout: chat scrolls in a region, input pinned at the
        # bottom. Only activates on a real TTY (SHIPIT_NO_TUI=1 opts out);
        # everywhere else the loop behaves exactly as before.
        term = BottomInputTerminal()
        if input_fn is input and term.enabled:
            term.start()
            input_fn = term.read
            output = term.print
        self._banner(output)
        try:
            return self._run_loop(input_fn=input_fn, output=output)
        finally:
            term.stop()

    def _run_loop(self, *, input_fn, output) -> int:
        while True:
            try:
                line = input_fn(bold(cyan("you ▸ ")))
            except (EOFError, KeyboardInterrupt):
                output()
                output(dim("[chat] bye"))
                return 0

            line = line.strip()
            if not line:
                continue

            if line == "/":
                # Bare slash → show the command dropdown like Claude Code.
                self._print_command_dropdown(output)
                continue

            if line.startswith("/"):
                exit_code = self.handle_command(line, output=output)
                if exit_code is not None:
                    return exit_code
                continue

            self.handle_user_turn(line, output=output)

    # ---- agent lifecycle -----------------------------------------------

    def _make_agent(self) -> Any:
        return make_agent(
            self.agent_type,
            llm=self.llm,
            rag=self.rag,
            workspace_root=self.workspace_root,
            use_builtins=self.use_builtins,
            goal_objective=self.goal_objective,
            goal_criteria=self.goal_criteria,
            reflect=self.reflect,
            verify=self.verify,
        )

    def _rebuild_agent(self, output) -> None:
        self.agent = self._make_agent()
        self.chat = agent_chat_session(
            self.agent,
            session_id=self.session_id,
            session_store=self.session_store,
        )
        output(dim(f"[chat] active agent: {magenta(self.agent_type)}"))

    # ---- command + turn handlers ---------------------------------------

    def _make_renderer(self) -> Any:
        """The transcript renderer for a turn.

        Defaults to the compact transcript: one line per tool call with a short
        result, as Claude Code prints it. `/style modern` is the Narrator
        (human verbs, collapsed work runs); `/style rich` or `/style plain`
        show every line of tool output.
        """
        style = getattr(self, "render_style", "compact")
        if style == "compact":
            from shipit_agent.narrate.compact import CompactRenderer

            return CompactRenderer(
                color=not self.quiet and sys.stdout.isatty(),
                show_footer=not self.quiet,
                model=current_model_name(self.provider),
            )
        if style == "modern":
            from shipit_agent.narrate import NarratorRenderer

            return NarratorRenderer(
                style="plain" if self.quiet else "auto",
                show_footer=not self.quiet,
                model=current_model_name(self.provider),
            )
        from shipit_agent.observability.activity import StreamRenderer

        return StreamRenderer(
            style="plain" if self.quiet else style, show_summary=False
        )

    def handle_user_turn(self, user_text: str, *, output=print) -> None:
        try:
            final_text = ""
            captured_sources: list[Any] = []
            saw_delta = False

            if self.chat is not None:
                events = self.chat.stream(user_text)
            else:
                events = stream_any_agent(self.agent, user_text)

            renderer = self._make_renderer()
            output()
            for event in events:
                etype = getattr(event, "type", "")
                if etype == "run_completed":
                    payload_out = (
                        event.payload.get("output")
                        if hasattr(event, "payload")
                        else None
                    )
                    final_text = payload_out or final_text
                    if getattr(self, "render_style", "compact") in ("compact", "modern"):
                        # These renderers close the turn themselves: they print the
                        # answer when the adapter never streamed, and the
                        # tokens/cost footer either way.
                        renderer.feed(event)
                        saw_delta = True
                    continue
                if etype == "rag_sources":
                    captured_sources = list(event.payload.get("sources", [])) or []
                    continue
                if etype == "text_delta":
                    saw_delta = True
                if not self.quiet or etype == "text_delta":
                    renderer.feed(event)
            renderer.close()

            if not final_text and self.chat is not None:
                for msg in reversed(self.chat.history()):
                    if msg.role == "assistant" and msg.content:
                        final_text = msg.content
                        break

            self.last_sources = captured_sources
            if saw_delta:
                # Answer already streamed inline — just close the turn.
                output()
            else:
                output()
                header = green("agent ▸ ")
                if final_text:
                    sys.stdout.write(header)
                    sys.stdout.flush()
                    typewriter(
                        final_text, output=output, enabled=self.typewriter_enabled
                    )
                else:
                    output(header + dim("(no answer)"))
            if captured_sources:
                output(
                    dim(f"  ({len(captured_sources)} RAG source(s) — /sources to see)")
                )
        except Exception as exc:
            output(red(f"[chat] error: {exc}"))

    # ---- command implementations ---------------------------------------
