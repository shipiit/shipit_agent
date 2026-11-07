"""What the chat prints: the banner, help, agents, tools, sources, RAG, history, info."""

from __future__ import annotations

from .agents import AGENT_TYPES, agent_tools
from .providers import PROVIDER_MODEL_ENV, PROVIDER_NAMES, current_model_name
from .style import banner, bold, cyan, dim, green, magenta, red, yellow


class ViewsMixin:
    """What the chat prints: the banner, help, agents, tools, sources, RAG, history, info."""

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
