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

from .agents import (
    AGENT_TYPES,
    agent_chat_session,
    agent_tools,
    make_agent,
    run_any_agent,
    stream_any_agent,
)
from .main import build_parser, main
from .providers import (
    PROVIDER_MODEL_ENV,
    PROVIDER_NAMES,
    build_llm,
    current_model_name,
    current_provider_name,
)
from .repl import ChatREPL
from .style import (
    EVENT_STYLE,
    Spinner,
    banner,
    blue,
    bold,
    cyan,
    dim,
    format_event,
    green,
    magenta,
    red,
    typewriter,
    yellow,
)

__all__ = [
    "AGENT_TYPES",
    "ChatREPL",
    "EVENT_STYLE",
    "PROVIDER_MODEL_ENV",
    "PROVIDER_NAMES",
    "Spinner",
    "agent_chat_session",
    "agent_tools",
    "banner",
    "blue",
    "bold",
    "build_llm",
    "build_parser",
    "current_model_name",
    "current_provider_name",
    "cyan",
    "dim",
    "format_event",
    "green",
    "magenta",
    "main",
    "make_agent",
    "red",
    "run_any_agent",
    "stream_any_agent",
    "typewriter",
    "yellow",
]
