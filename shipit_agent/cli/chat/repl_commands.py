"""Slash commands, and switching provider, model, agent and style."""

from __future__ import annotations

import os

from .agents import AGENT_TYPES
from .providers import PROVIDER_MODEL_ENV, PROVIDER_NAMES, build_llm, current_model_name
from .style import cyan, dim, magenta, red, yellow


class CommandsMixin:
    """Slash commands, and switching provider, model, agent and style."""

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
        if cmd == "/style":
            self._set_style(arg, output)
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
            output(red(f"[chat] usage: /provider <{'|'.join(PROVIDER_NAMES)}>"))
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

    def _set_style(self, arg: str, output) -> None:
        """`/style compact|modern|rich|plain` — switch the transcript renderer."""
        choice = (arg or "").strip().lower()
        if choice not in ("compact", "modern", "rich", "plain"):
            output(dim(f"  style: {self.render_style}  (compact | modern | rich | plain)"))
            return
        self.render_style = choice
        output(dim(f"  style → {choice}"))

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
