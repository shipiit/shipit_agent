"""Modern interactive chat REPL — supports every Shipit agent type.

Run with::

    shipit chat                       # default: DeepAgent
    shipit chat --agent agent         # plain Agent
    shipit chat --agent deep          # DeepAgent (default)
    shipit chat --agent goal          # GoalAgent
    shipit chat --agent reflective    # ReflectiveAgent
    shipit chat --agent adaptive      # AdaptiveAgent
    shipit chat --agent supervisor    # Supervisor (multi-worker)
    shipit chat --agent persistent    # PersistentAgent (checkpointed)

Features:

- One CLI for all agent types — switch live with ``/agent <type>``.
- RAG-aware out of the box: ``--rag-file <path>`` indexes a file before
  the session starts; ``/index <path>`` indexes one mid-session.
- Live event streaming with a quiet toggle (``/quiet``).
- Slash commands for tools, sources, history, save/load, reset, and
  more.
- Rich terminal rendering with colour and box-drawing characters when
  the output is a TTY; falls back to plain text otherwise.
- Pluggable LLM provider via ``--provider`` (or ``$SHIPIT_LLM_PROVIDER``).
- Sessions persist to disk with ``--session-dir`` so chats survive
  restarts.

Slash commands::

    /help                show all slash commands
    /agent <type>        switch agent type live (agent|deep|goal|...)
    /agents              list available agent types
    /tools               list the agent's tools
    /sources             show RAG sources from the last turn
    /index <path>        index a file into the active RAG
    /rag                 print RAG stats (chunks, sources)
    /goal <objective>    set a goal (only works with --agent goal/deep)
    /reflect on|off      toggle reflective mode (DeepAgent only)
    /verify on|off       toggle verification mode (DeepAgent only)
    /history             print conversation history
    /clear               clear conversation history
    /save <path>         save the conversation as JSON
    /load <path>         load a saved conversation
    /reset               start a fresh session
    /quiet               toggle event streaming
    /info                show agent + session info
    /exit, /quit         leave the chat
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from shipit_agent.models import Message
from shipit_agent.stores import FileSessionStore, InMemorySessionStore

try:  # readline is unix-only but ships with mac/linux Python builds
    import readline  # type: ignore

    _HAS_READLINE = True
except Exception:  # pragma: no cover
    readline = None  # type: ignore
    _HAS_READLINE = False


# ----------------------------------------------------------------------------
# ANSI / rich rendering
# ----------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _ansi(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def dim(t: str) -> str:
    return _ansi(t, "2")


def bold(t: str) -> str:
    return _ansi(t, "1")


def cyan(t: str) -> str:
    return _ansi(t, "36")


def green(t: str) -> str:
    return _ansi(t, "32")


def yellow(t: str) -> str:
    return _ansi(t, "33")


def red(t: str) -> str:
    return _ansi(t, "31")


def magenta(t: str) -> str:
    return _ansi(t, "35")


def blue(t: str) -> str:
    return _ansi(t, "34")


def banner(title: str, subtitle: str = "") -> str:
    width = max(len(title), len(subtitle)) + 4
    top = "╭" + "─" * (width - 2) + "╮"
    bot = "╰" + "─" * (width - 2) + "╯"
    parts = [magenta(top), magenta("│ ") + bold(title.ljust(width - 4)) + magenta(" │")]
    if subtitle:
        parts.append(magenta("│ ") + dim(subtitle.ljust(width - 4)) + magenta(" │"))
    parts.append(magenta(bot))
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Event rendering, typewriter, and provider/model metadata
# ----------------------------------------------------------------------------


EVENT_STYLE: dict[str, tuple[str, str]] = {
    "run_started": ("▶", "34"),
    "reasoning_started": ("✧", "35"),
    "reasoning_completed": ("✓", "35"),
    "step_started": ("·", "2"),
    "planning_started": ("◐", "33"),
    "planning_completed": ("◑", "33"),
    "tool_called": ("⚙", "36"),
    "tool_completed": ("✓", "32"),
    "tool_failed": ("✗", "31"),
    "mcp_attached": ("⧉", "34"),
    "llm_retry": ("↻", "33"),
    "tool_retry": ("↻", "33"),
    "interactive_request": ("?", "33"),
    "context_snapshot": ("◆", "2"),
    "rag_sources": ("❀", "35"),
    "run_completed": ("■", "32"),
}


def format_event(event: Any) -> str:
    etype = getattr(event, "type", "event")
    icon, color = EVENT_STYLE.get(etype, ("·", "2"))
    msg = getattr(event, "message", "") or ""
    payload = getattr(event, "payload", {}) or {}
    extra = ""
    if etype == "tool_called":
        name = payload.get("name") or payload.get("tool") or ""
        if name:
            extra = dim(f"  → {name}")
    elif etype == "tool_completed":
        name = payload.get("name") or payload.get("tool") or ""
        if name:
            extra = dim(f"  ← {name}")
    elif etype == "tool_failed":
        err = payload.get("error", "")
        extra = dim(f"  {str(err)[:60]}")
    return f"  {_ansi(icon, color)} {_ansi(etype, '2')} {msg}{extra}"


def typewriter(
    text: str,
    *,
    output,
    chunk_size: int = 3,
    delay: float = 0.012,
    enabled: bool = True,
) -> None:
    """Print text with a gentle typewriter effect when writing to a TTY."""
    if not text:
        return
    if not enabled or not _USE_COLOR:
        output(text)
        return
    try:
        for i in range(0, len(text), chunk_size):
            sys.stdout.write(text[i : i + chunk_size])
            sys.stdout.flush()
            time.sleep(delay)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception:
        output(text)


class Spinner:
    """Lightweight single-line activity indicator for TTYs."""

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "thinking") -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = _USE_COLOR and sys.stdout.isatty()

    def _run(self) -> None:
        it = itertools.cycle(self._FRAMES)
        while not self._stop.is_set():
            frame = next(it)
            try:
                sys.stdout.write(f"\r  {magenta(frame)} {dim(self.label)}   ")
                sys.stdout.flush()
            except Exception:
                return
            time.sleep(0.08)
        try:
            sys.stdout.write("\r" + " " * (len(self.label) + 8) + "\r")
            sys.stdout.flush()
        except Exception:
            pass

    def start(self) -> None:
        if not self._enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, label: str) -> None:
        self.label = label

    def stop(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)


PROVIDER_MODEL_ENV = {
    "bedrock": ("SHIPIT_BEDROCK_MODEL", "bedrock/openai.gpt-oss-120b-1:0"),
    "openai": ("SHIPIT_OPENAI_MODEL", "gpt-4o-mini"),
    "anthropic": ("SHIPIT_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
    "gemini": ("SHIPIT_GEMINI_MODEL", "gemini/gemini-1.5-pro"),
    "vertex": ("SHIPIT_VERTEX_MODEL", "vertex_ai/gemini-1.5-pro"),
    "groq": ("SHIPIT_GROQ_MODEL", "groq/llama-3.3-70b-versatile"),
    "together": (
        "SHIPIT_TOGETHER_MODEL",
        "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
    ),
    "ollama": ("SHIPIT_OLLAMA_MODEL", "ollama/llama3.1"),
    "litellm": ("SHIPIT_LITELLM_MODEL", ""),
}

PROVIDER_NAMES = tuple(PROVIDER_MODEL_ENV.keys())


def current_provider_name(explicit: str | None = None) -> str:
    return (explicit or os.getenv("SHIPIT_LLM_PROVIDER", "bedrock")).strip().lower()


def current_model_name(provider: str) -> str:
    env_var, default = PROVIDER_MODEL_ENV.get(provider, ("", ""))
    if not env_var:
        return "(n/a)"
    return os.getenv(env_var, default) or "(unset)"


# ----------------------------------------------------------------------------
# LLM loader — reuses examples/run_multi_tool_agent.build_llm_from_env
# ----------------------------------------------------------------------------


def build_llm(provider: str | None = None) -> Any:
    try:
        from examples.run_multi_tool_agent import build_llm_from_env

        return build_llm_from_env(provider)
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(
            yellow(f"[chat] Could not build a real LLM ({exc}); using SimpleEchoLLM.\n")
        )
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()


# ----------------------------------------------------------------------------
# Agent factories — one shape for every agent type
# ----------------------------------------------------------------------------


AGENT_TYPES = (
    "agent",
    "deep",
    "goal",
    "reflective",
    "adaptive",
    "supervisor",
    "persistent",
)


def make_agent(
    agent_type: str,
    *,
    llm: Any,
    rag: Any = None,
    workspace_root: str = ".shipit_workspace",
    use_builtins: bool = True,
    goal_objective: str | None = None,
    goal_criteria: list[str] | None = None,
    reflect: bool = False,
    verify: bool = False,
) -> Any:
    """Build an agent of the requested type, fully wired for chat."""
    from shipit_agent import Agent
    from shipit_agent.deep import (
        AdaptiveAgent,
        DeepAgent,
        Goal,
        GoalAgent,
        PersistentAgent,
        ReflectiveAgent,
        Supervisor,
    )

    agent_type = agent_type.lower()
    if agent_type == "agent":
        if use_builtins:
            return Agent.with_builtins(llm=llm, workspace_root=workspace_root, rag=rag)
        return Agent(llm=llm, rag=rag)

    if agent_type == "deep":
        return (DeepAgent.with_builtins if use_builtins else DeepAgent)(
            llm=llm,
            workspace_root=workspace_root,
            rag=rag,
            reflect=reflect,
            verify=verify,
        )

    if agent_type == "goal":
        objective = goal_objective or "Help the user with their request."
        criteria = goal_criteria or ["Answer addresses the user's question."]
        return GoalAgent.with_builtins(
            llm=llm,
            goal=Goal(objective=objective, success_criteria=criteria),
            rag=rag,
        )

    if agent_type == "reflective":
        return ReflectiveAgent.with_builtins(llm=llm, rag=rag)

    if agent_type == "adaptive":
        return AdaptiveAgent.with_builtins(llm=llm, rag=rag)

    if agent_type == "supervisor":
        return Supervisor.with_builtins(
            llm=llm,
            worker_configs=[
                {
                    "name": "researcher",
                    "prompt": "You research information thoroughly.",
                },
                {"name": "writer", "prompt": "You write clear, concise answers."},
            ],
            rag=rag,
        )

    if agent_type == "persistent":
        return PersistentAgent(
            llm=llm,
            checkpoint_dir=os.path.join(workspace_root, "checkpoints"),
            rag=rag,
        )

    raise ValueError(f"Unknown agent type: {agent_type}. Choose from {AGENT_TYPES}.")


def stream_any_agent(agent: Any, user_text: str):
    """Stream from any agent type, normalising the interface."""
    if hasattr(agent, "stream"):
        # Most agents take user_text; some (GoalAgent) ignore the prompt.
        try:
            yield from agent.stream(user_text)
            return
        except TypeError:
            yield from agent.stream()
            return
    # Fallback: synchronous run
    result = run_any_agent(agent, user_text)
    from shipit_agent.models import AgentEvent

    yield AgentEvent(
        type="run_completed",
        message="run completed",
        payload={"output": getattr(result, "output", str(result))},
    )


def run_any_agent(agent: Any, user_text: str) -> Any:
    if hasattr(agent, "run"):
        try:
            return agent.run(user_text)
        except TypeError:
            return agent.run()
    raise TypeError(f"Agent {agent.__class__.__name__} has no run() method")


def agent_tools(agent: Any) -> list[Any]:
    if hasattr(agent, "tools"):
        return list(agent.tools)
    if hasattr(agent, "agent") and hasattr(agent.agent, "tools"):
        return list(agent.agent.tools)
    return []


def agent_chat_session(agent: Any, *, session_id: str, session_store: Any) -> Any:
    """Return an AgentChatSession-compatible object for the given agent."""
    from shipit_agent.chat_session import AgentChatSession

    inner = agent
    # DeepAgent / wrappers expose .agent for the underlying Agent.
    if hasattr(agent, "agent") and hasattr(agent.agent, "run"):
        inner = agent.agent
    if hasattr(inner, "run") and hasattr(inner, "stream"):
        return AgentChatSession(
            agent=inner,
            session_id=session_id,
            session_store=session_store,
        )
    return None  # Goal/Supervisor/etc. — fall back to direct stream


# ----------------------------------------------------------------------------
# REPL
# ----------------------------------------------------------------------------


class ChatREPL:
    """Modern multi-agent chat REPL."""

    SLASH_COMMANDS = (
        "/help",
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

        self.agent = self._make_agent()
        self.chat = agent_chat_session(
            self.agent,
            session_id=self.session_id,
            session_store=self.session_store,
        )

    # ---- public entry points -------------------------------------------

    def run(self, *, input_fn=input, output=print) -> int:
        self._install_readline()
        self._banner(output)
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

    def _install_readline(self) -> None:
        if not _HAS_READLINE:
            return
        try:
            readline.set_completer_delims(" \t\n")
            readline.parse_and_bind("tab: complete")
            readline.set_completer(self._readline_completer)
        except Exception:
            pass

    def _readline_completer(self, text: str, state: int):
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = text
        stripped = line.lstrip()
        candidates: list[str] = []
        if stripped.startswith("/"):
            # First word → slash command
            parts = stripped.split(" ", 1)
            if len(parts) == 1:
                candidates = [c for c in self.SLASH_COMMANDS if c.startswith(text)]
            else:
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                if cmd == "/agent":
                    candidates = [t for t in AGENT_TYPES if t.startswith(arg)]
                elif cmd == "/provider":
                    candidates = [p for p in PROVIDER_NAMES if p.startswith(arg)]
        try:
            return candidates[state]
        except IndexError:
            return None

    def _print_command_dropdown(self, output) -> None:
        output(dim("─ slash commands ─"))
        rows = [
            ("/help", "show this help"),
            ("/agent <type>", f"switch agent type ({'|'.join(AGENT_TYPES)})"),
            ("/agents", "list available agent types"),
            ("/provider <name>", f"switch LLM provider ({'|'.join(PROVIDER_NAMES)})"),
            ("/model <name>", "set the model for the current provider"),
            ("/tools", "list the agent's tools"),
            ("/sources", "RAG sources from the last turn"),
            ("/index <path>", "index a file into RAG"),
            ("/rag", "show RAG stats"),
            ("/goal <obj>", "set a goal (goal/deep agents)"),
            ("/reflect on|off", "toggle reflective mode (DeepAgent)"),
            ("/verify on|off", "toggle verification mode (DeepAgent)"),
            ("/history", "print conversation history"),
            ("/clear", "clear conversation history"),
            ("/save <path>", "save the conversation as JSON"),
            ("/load <path>", "load a saved conversation"),
            ("/reset", "start a fresh session"),
            ("/quiet", "toggle event streaming visibility"),
            ("/stream on|off", "toggle typewriter streaming effect"),
            ("/info", "show agent + session info"),
            ("/exit, /quit", "leave the chat"),
        ]
        for cmd, desc in rows:
            output(f"  {cyan(cmd):28s}  {dim(desc)}")
        output(dim("tip: press <TAB> after typing / to autocomplete"))

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

    def handle_command(self, line: str, *, output=print) -> int | None:
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in {"/exit", "/quit"}:
            output(dim("[chat] bye"))
            return 0
        if cmd == "/help":
            self._print_help(output)
            return None
        if cmd == "/agent":
            self._switch_agent(arg, output)
            return None
        if cmd == "/agents":
            self._print_agent_types(output)
            return None
        if cmd == "/tools":
            self._print_tools(output)
            return None
        if cmd == "/sources":
            self._print_sources(output)
            return None
        if cmd == "/index":
            self._index_file(arg, output)
            return None
        if cmd == "/rag":
            self._print_rag(output)
            return None
        if cmd == "/goal":
            self._set_goal(arg, output)
            return None
        if cmd == "/reflect":
            self._toggle_reflect(arg, output)
            return None
        if cmd == "/verify":
            self._toggle_verify(arg, output)
            return None
        if cmd == "/history":
            self._print_history(output)
            return None
        if cmd == "/clear":
            self._clear_history(output)
            return None
        if cmd == "/save":
            self._save_history(arg, output)
            return None
        if cmd == "/load":
            self._load_history(arg, output)
            return None
        if cmd == "/reset":
            self._reset_session(output)
            return None
        if cmd == "/quiet":
            self.quiet = not self.quiet
            output(dim(f"[chat] event stream {'hidden' if self.quiet else 'visible'}"))
            return None
        if cmd == "/stream":
            self.typewriter_enabled = self._parse_bool(arg, self.typewriter_enabled)
            output(
                dim(
                    f"[chat] typewriter streaming {'on' if self.typewriter_enabled else 'off'}"
                )
            )
            return None
        if cmd == "/provider":
            self._switch_provider(arg, output)
            return None
        if cmd == "/model":
            self._switch_model(arg, output)
            return None
        if cmd == "/info":
            self._print_info(output)
            return None

        output(red(f"[chat] unknown command: {cmd}. Try /help."))
        return None

    def _switch_provider(self, target: str, output) -> None:
        target = target.strip().lower()
        if not target:
            output(red(f"[chat] usage: /provider <{ '|'.join(PROVIDER_NAMES) }>"))
            return
        if target not in PROVIDER_MODEL_ENV:
            output(
                red(
                    f"[chat] unknown provider: {target}. Options: {', '.join(PROVIDER_NAMES)}"
                )
            )
            return
        os.environ["SHIPIT_LLM_PROVIDER"] = target
        try:
            self.llm = build_llm(target)
        except Exception as exc:
            output(red(f"[chat] failed to build provider {target}: {exc}"))
            return
        self.provider = target
        self._rebuild_agent(output)
        output(
            dim(
                f"[chat] provider → {magenta(target)}  model → {cyan(current_model_name(target))}"
            )
        )

    def _switch_model(self, target: str, output) -> None:
        target = target.strip()
        if not target:
            env_var, _ = PROVIDER_MODEL_ENV.get(self.provider, ("", ""))
            output(red(f"[chat] usage: /model <model-id>  (sets {env_var or 'n/a'})"))
            return
        env_var, _ = PROVIDER_MODEL_ENV.get(self.provider, ("", ""))
        if not env_var:
            output(
                red(
                    f"[chat] provider {self.provider} has no configurable model env var"
                )
            )
            return
        os.environ[env_var] = target
        try:
            self.llm = build_llm(self.provider)
        except Exception as exc:
            output(red(f"[chat] failed to reload LLM with model {target}: {exc}"))
            return
        self._rebuild_agent(output)
        output(dim(f"[chat] model → {cyan(target)}  (env {env_var})"))

    def handle_user_turn(self, user_text: str, *, output=print) -> None:
        try:
            final_text = ""
            captured_sources: list[Any] = []

            if self.chat is not None:
                events = self.chat.stream(user_text)
            else:
                events = stream_any_agent(self.agent, user_text)

            spinner = Spinner(label="thinking")
            spinner.start()
            try:
                for event in events:
                    etype = getattr(event, "type", "")
                    if etype == "run_completed":
                        payload_out = (
                            event.payload.get("output")
                            if hasattr(event, "payload")
                            else None
                        )
                        final_text = payload_out or final_text
                        continue
                    if etype == "rag_sources":
                        captured_sources = list(event.payload.get("sources", [])) or []
                        continue
                    # Update spinner label for context; print line if not quiet
                    if etype:
                        spinner.update(etype.replace("_", " "))
                    if not self.quiet:
                        # Clear the spinner line, print the event, spinner resumes.
                        sys.stdout.write("\r" + " " * 60 + "\r")
                        output(format_event(event))
            finally:
                spinner.stop()

            if not final_text and self.chat is not None:
                for msg in reversed(self.chat.history()):
                    if msg.role == "assistant" and msg.content:
                        final_text = msg.content
                        break

            self.last_sources = captured_sources
            output()
            header = green("agent ▸ ")
            if final_text:
                sys.stdout.write(header)
                sys.stdout.flush()
                typewriter(final_text, output=output, enabled=self.typewriter_enabled)
            else:
                output(header + dim("(no answer)"))
            if captured_sources:
                output(
                    dim(f"  ({len(captured_sources)} RAG source(s) — /sources to see)")
                )
        except Exception as exc:
            output(red(f"[chat] error: {exc}"))

    # ---- command implementations ---------------------------------------

    def _banner(self, output) -> None:
        provider = self.provider
        model = current_model_name(provider)
        env_var, _default = PROVIDER_MODEL_ENV.get(provider, ("", ""))

        output(
            banner(
                "Shipit Agent — interactive chat",
                f"agent={self.agent_type}  session={self.session_id}",
            )
        )

        # Current LLM line
        output(
            "  "
            + dim("provider: ")
            + magenta(provider)
            + dim("   model: ")
            + cyan(model)
        )

        # How-to-change instructions (first-screen tutorial)
        output()
        output(bold("How to change the provider or model:"))
        output(
            "  "
            + cyan("/provider <name>")
            + dim(f"   live-switch provider  ({', '.join(PROVIDER_NAMES)})")
        )
        output(
            "  "
            + cyan("/model <id>")
            + dim(f"       set model for {provider} (env: {env_var or 'n/a'})")
        )
        output("  " + cyan("shipit chat --provider openai") + dim("   on launch"))
        output(
            "  "
            + cyan("export SHIPIT_LLM_PROVIDER=anthropic")
            + dim("   persistently in your shell or .env")
        )

        output()
        output(
            dim("press ")
            + bold("/")
            + dim(" + ")
            + bold("<TAB>")
            + dim(" to see all commands  ·  type ")
            + bold("/help")
            + dim(" for the full list  ·  ")
            + bold("/exit")
            + dim(" to quit")
        )
        output()

    def _print_help(self, output) -> None:
        output(bold("Slash commands:"))
        rows = [
            ("/help", "show this help"),
            ("/agent <type>", f"switch agent type ({'|'.join(AGENT_TYPES)})"),
            ("/agents", "list available agent types"),
            ("/provider <name>", f"switch LLM provider ({'|'.join(PROVIDER_NAMES)})"),
            ("/model <id>", "set the model id for the current provider"),
            ("/tools", "list the agent's tools"),
            ("/sources", "show RAG sources from the last turn"),
            ("/index <path>", "index a file into the active RAG"),
            ("/rag", "show RAG stats"),
            ("/goal <objective>", "set a goal (use with --agent goal/deep)"),
            ("/reflect on|off", "toggle reflective mode (DeepAgent)"),
            ("/verify on|off", "toggle verification mode (DeepAgent)"),
            ("/history", "print conversation history"),
            ("/clear", "clear conversation history"),
            ("/save <path>", "save the conversation as JSON"),
            ("/load <path>", "load a saved conversation"),
            ("/reset", "start a fresh session"),
            ("/quiet", "toggle event stream visibility"),
            ("/stream on|off", "toggle typewriter streaming effect"),
            ("/info", "show agent + session info"),
            ("/exit, /quit", "leave the chat"),
        ]
        for cmd, desc in rows:
            output(f"  {cyan(cmd):28s}  {dim(desc)}")
        output(
            dim("tip: type just ")
            + bold("/")
            + dim(" to open the command dropdown; press <TAB> to autocomplete.")
        )

    def _print_agent_types(self, output) -> None:
        output(bold("Available agent types:"))
        descriptions = {
            "agent": "Plain Agent — direct tool use, fast",
            "deep": "DeepAgent — planning, workspace, sub-agents, verification",
            "goal": "GoalAgent — decompose → execute → self-evaluate",
            "reflective": "ReflectiveAgent — generate → critique → revise",
            "adaptive": "AdaptiveAgent — can write new tools at runtime",
            "supervisor": "Supervisor — coordinates multiple worker agents",
            "persistent": "PersistentAgent — checkpointed long-running tasks",
        }
        for name in AGENT_TYPES:
            marker = green("●") if name == self.agent_type else dim("○")
            output(f"  {marker} {cyan(name):14s}  {dim(descriptions[name])}")
        output()
        output(dim("Switch with: /agent <type>"))

    def _switch_agent(self, target: str, output) -> None:
        target = target.strip().lower()
        if not target:
            output(red("[chat] usage: /agent <type>"))
            return
        if target not in AGENT_TYPES:
            output(red(f"[chat] unknown agent type: {target}. Try /agents."))
            return
        self.agent_type = target
        self._rebuild_agent(output)

    def _print_tools(self, output) -> None:
        tools = agent_tools(self.agent)
        output(bold(f"{len(tools)} tools:"))
        for t in tools:
            name = getattr(t, "name", t.__class__.__name__)
            desc = (getattr(t, "description", "") or "").replace("\n", " ")
            output(f"  · {cyan(name):28s} {dim(desc[:80])}")

    def _print_sources(self, output) -> None:
        if not self.last_sources:
            output(dim("[chat] no RAG sources captured in the last turn"))
            return
        output(bold(f"{len(self.last_sources)} RAG source(s):"))
        for s in self.last_sources:
            idx = s.get("index") if isinstance(s, dict) else getattr(s, "index", "?")
            src = s.get("source") if isinstance(s, dict) else getattr(s, "source", None)
            chunk_id = (
                s.get("chunk_id")
                if isinstance(s, dict)
                else getattr(s, "chunk_id", "?")
            )
            text = s.get("text") if isinstance(s, dict) else getattr(s, "text", "")
            output(f"  [{idx}] {cyan(str(src))} (chunk {chunk_id})")
            output(f"      {dim(text[:140])}")

    def _index_file(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /index <path>"))
            return
        if self.rag is None:
            self._init_default_rag(output)
        try:
            chunks = self.rag.index_file(path)
            output(dim(f"[chat] indexed {len(chunks)} chunks from {path}"))
            self._rebuild_agent(output)
        except Exception as exc:
            output(red(f"[chat] index failed: {exc}"))

    def _init_default_rag(self, output) -> None:
        from shipit_agent.rag import RAG, HashingEmbedder

        self.rag = RAG.default(embedder=HashingEmbedder(dimension=512))
        output(dim("[chat] initialised default in-memory RAG (HashingEmbedder)"))

    def _print_rag(self, output) -> None:
        if self.rag is None:
            output(dim("[chat] no RAG attached"))
            return
        try:
            output(bold("RAG stats:"))
            output(f"  chunks  : {self.rag.count()}")
            output(f"  sources : {len(self.rag.list_sources())}")
            for s in self.rag.list_sources()[:20]:
                output(f"    · {s}")
        except Exception as exc:
            output(red(f"[chat] RAG inspection failed: {exc}"))

    def _set_goal(self, objective: str, output) -> None:
        if not objective:
            output(red("[chat] usage: /goal <objective>"))
            return
        self.goal_objective = objective
        self.goal_criteria = ["Answer addresses the user's question."]
        if self.agent_type not in {"goal", "deep"}:
            output(dim(f"[chat] switching to goal agent — was {self.agent_type}"))
            self.agent_type = "goal"
        self._rebuild_agent(output)
        output(dim(f"[chat] goal set: {objective}"))

    def _toggle_reflect(self, arg: str, output) -> None:
        if self.agent_type != "deep":
            output(yellow("[chat] /reflect only applies to --agent deep"))
            return
        self.reflect = self._parse_bool(arg, self.reflect)
        self._rebuild_agent(output)
        output(dim(f"[chat] reflect = {self.reflect}"))

    def _toggle_verify(self, arg: str, output) -> None:
        if self.agent_type != "deep":
            output(yellow("[chat] /verify only applies to --agent deep"))
            return
        self.verify = self._parse_bool(arg, self.verify)
        self._rebuild_agent(output)
        output(dim(f"[chat] verify = {self.verify}"))

    @staticmethod
    def _parse_bool(arg: str, default: bool) -> bool:
        s = arg.strip().lower()
        if s in {"on", "true", "1", "yes", "y"}:
            return True
        if s in {"off", "false", "0", "no", "n"}:
            return False
        return not default

    def _print_history(self, output) -> None:
        if self.chat is None:
            output(dim("[chat] this agent type does not expose history"))
            return
        history = self.chat.history()
        output(bold(f"{len(history)} message(s):"))
        for msg in history:
            colour = (
                green
                if msg.role == "assistant"
                else cyan
                if msg.role == "user"
                else yellow
            )
            output(f"  {colour(msg.role):20s} {msg.content[:200]}")

    def _clear_history(self, output) -> None:
        if self.chat is None:
            output(dim("[chat] no history to clear"))
            return
        record = self.session_store.load(self.session_id)
        if record:
            record.messages.clear()
            self.session_store.save(record)
        output(dim("[chat] history cleared"))

    def _reset_session(self, output) -> None:
        new_id = f"chat-{uuid.uuid4().hex[:8]}"
        self.session_id = new_id
        self.last_sources = []
        self._rebuild_agent(output)
        output(dim(f"[chat] new session: {new_id}"))

    def _save_history(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /save <path>"))
            return
        if self.chat is None:
            output(dim("[chat] this agent type has no chat history"))
            return
        history = self.chat.history()
        data = {
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "messages": [
                {"role": m.role, "content": m.content, "name": m.name} for m in history
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        output(dim(f"[chat] saved {len(history)} messages → {path}"))

    def _load_history(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /load <path>"))
            return
        if not os.path.exists(path):
            output(red(f"[chat] file not found: {path}"))
            return
        if self.chat is None:
            output(
                dim(
                    "[chat] current agent type has no chat history; switch to /agent agent or /agent deep first."
                )
            )
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        new_id = data.get("session_id", f"chat-{uuid.uuid4().hex[:8]}")
        self.session_id = new_id
        if data.get("agent_type") and data["agent_type"] != self.agent_type:
            self.agent_type = data["agent_type"]
            self._rebuild_agent(output)
        else:
            self._rebuild_agent(output)
        record = self.session_store.load(new_id)
        if record is None:
            from shipit_agent.stores.session import SessionRecord

            record = SessionRecord(session_id=new_id, messages=[])
        record.messages = [
            Message(role=m["role"], content=m["content"], name=m.get("name"))
            for m in data.get("messages", [])
        ]
        self.session_store.save(record)
        output(dim(f"[chat] loaded {len(record.messages)} messages from {path}"))

    def _print_info(self, output) -> None:
        output(bold("Session info:"))
        output(f"  agent_type    : {magenta(self.agent_type)}")
        output(f"  provider      : {magenta(self.provider)}")
        output(f"  model         : {cyan(current_model_name(self.provider))}")
        output(f"  session_id    : {cyan(self.session_id)}")
        output(f"  workspace     : {self.workspace_root}")
        output(f"  builtins      : {self.use_builtins}")
        output(f"  reflect       : {self.reflect}")
        output(f"  verify        : {self.verify}")
        output(f"  streaming     : {'on' if self.typewriter_enabled else 'off'}")
        output(f"  rag attached  : {self.rag is not None}")
        if self.rag is not None:
            try:
                output(f"  rag chunks    : {self.rag.count()}")
            except Exception:
                pass
        output(f"  tools         : {len(agent_tools(self.agent))}")


# ----------------------------------------------------------------------------
# argparse + entry point
# ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shipit-chat",
        description="Modern interactive chat with any Shipit agent type.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              shipit chat
              shipit chat --agent agent
              shipit chat --agent deep --reflect --verify
              shipit chat --agent goal --goal "Build a todo CLI" --criteria "tests pass"
              shipit chat --rag-file docs/manual.pdf
              shipit chat --provider anthropic --session-dir ~/.shipit/sessions
        """),
    )
    parser.add_argument(
        "--agent",
        default="deep",
        choices=list(AGENT_TYPES),
        help="Agent type (default: deep)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (defaults to $SHIPIT_LLM_PROVIDER or 'bedrock')",
    )
    parser.add_argument(
        "--session-id", default=None, help="Resume a specific session id"
    )
    parser.add_argument(
        "--session-dir",
        default=None,
        help="Persist sessions to this directory (FileSessionStore)",
    )
    parser.add_argument(
        "--workspace",
        default=".shipit_workspace",
        help="Workspace root for the WorkspaceFilesTool",
    )
    parser.add_argument(
        "--no-builtins",
        action="store_true",
        help="Skip the regular built-in tool catalogue",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Hide intermediate event stream"
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable the typewriter streaming effect on the final answer",
    )
    parser.add_argument(
        "--rag-file",
        action="append",
        default=[],
        help="Index a file (txt/md/pdf/html) into RAG before the session starts. Repeatable.",
    )
    parser.add_argument(
        "--rag-dim",
        type=int,
        default=512,
        help="HashingEmbedder dimension when --rag-file is used (default 512)",
    )
    parser.add_argument(
        "--reflect", action="store_true", help="Enable reflective mode (DeepAgent)"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Enable verification mode (DeepAgent)"
    )
    parser.add_argument(
        "--goal", default=None, help="Goal objective (use with --agent goal)"
    )
    parser.add_argument(
        "--criteria",
        action="append",
        default=[],
        help="Goal success criterion (repeatable; use with --agent goal)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    llm = build_llm(args.provider)

    rag = None
    if args.rag_file:
        from shipit_agent.rag import RAG, HashingEmbedder

        rag = RAG.default(embedder=HashingEmbedder(dimension=args.rag_dim))
        for path in args.rag_file:
            try:
                chunks = rag.index_file(path)
                sys.stderr.write(
                    dim(f"[chat] indexed {len(chunks)} chunks from {path}\n")
                )
            except Exception as exc:
                sys.stderr.write(red(f"[chat] failed to index {path}: {exc}\n"))

    session_store: Any
    if args.session_dir:
        session_store = FileSessionStore(root=args.session_dir)
    else:
        session_store = InMemorySessionStore()

    repl = ChatREPL(
        llm=llm,
        agent_type=args.agent,
        provider=args.provider,
        rag=rag,
        workspace_root=args.workspace,
        use_builtins=not args.no_builtins,
        session_id=args.session_id,
        session_store=session_store,
        quiet=args.quiet,
        reflect=args.reflect,
        verify=args.verify,
        typewriter_enabled=not args.no_stream,
    )

    if args.goal:
        repl.goal_objective = args.goal
        repl.goal_criteria = args.criteria or ["Answer addresses the user's question."]
        if args.agent in {"goal", "deep"}:
            repl._rebuild_agent(print)

    return repl.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
