"""The use_app tool: run a saved app and return what it produced."""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.apps import (
    AppStore,
    app_docstring,
    run_app,
)
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.describe_binding.describe_binding_tool import (
    BINDINGS_STATE_KEY,
)
from shipit_agent.tools.execute_code.execute_code_tool import INVOKER_STATE_KEY
from shipit_agent.tools.formatting import clip_text

from .app_tool_base import _MAX_OUTPUT, _AppTool


class UseAppTool(_AppTool):
    """Run an app and return what it produced."""

    name = "use_app"
    read_only = False
    description = (
        "Run an app with input and get its result. Use this instead of redoing "
        "work the app already encodes."
    )

    def __init__(self, store: AppStore, *, timeout_seconds: float = 60.0) -> None:
        super().__init__(store)
        self.timeout_seconds = timeout_seconds

    def schema(self) -> dict[str, Any]:
        return self._function(
            self.name,
            self.description,
            {
                "app": {"type": "string", "description": "The app's name."},
                "input": {
                    "type": "object",
                    "description": "JSON object passed to the app's run(input, env).",
                },
            },
            ["app"],
        )

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        name = str(kwargs.get("app") or "")
        payload = kwargs.get("input")
        if isinstance(payload, str):
            # Small models routinely send the object as a JSON string.
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {"value": payload}

        try:
            app = self.store.get(name)
        except KeyError as exc:
            known = ", ".join(a.name for a in self.store.list()) or "none"
            return ToolOutput(
                text=f"{exc}. Apps available: {known}.",
                metadata={"error": "unknown_app"},
            )

        result = run_app(
            app,
            payload if isinstance(payload, dict) else {},
            invoker=context.state.get(INVOKER_STATE_KEY),
            bindings=context.state.get(BINDINGS_STATE_KEY) or {},
            timeout_seconds=self.timeout_seconds,
            # Run where the agent works, so a relative path in the input means
            # what the agent thinks it means.
            cwd=self.store.workdir,
        )

        parts = []
        if result.ok:
            parts.append(json.dumps(result.value, indent=2, default=str))
        else:
            parts.append(f"The app failed: {result.error or 'no result'}")
            # What the app says about itself, so the retry is informed rather
            # than another guess at the argument names.
            doc = app_docstring(app)
            if doc:
                parts.append(f"What `{app.name}` expects:\n{doc}")
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout}")

        metadata: dict[str, Any] = {
            "app": app.name,
            "ok": result.ok,
            "env_calls": result.env_calls,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "value": result.value,
        }
        # An app that wrote a file has made a *thing*. Declaring its path is
        # what turns it into a card in the transcript instead of a string
        # buried in the return value.
        produced = _produced_path(result.value)
        if produced:
            metadata["path"] = produced
            metadata["title"] = app.manifest.title or app.name

        return ToolOutput(
            text=clip_text("\n\n".join(parts), max_chars=_MAX_OUTPUT),
            metadata=metadata,
        )


def _produced_path(value: Any) -> str | None:
    """A file an app says it wrote, if it exists.

    Apps return whatever they like; by convention a produced file comes back
    under ``path``, ``file`` or ``output``. Only a path that is really on disk
    is reported — a plan is not an artifact.
    """
    from pathlib import Path

    if not isinstance(value, dict):
        return None
    for key in ("path", "file", "output", "output_path"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            try:
                if Path(candidate).is_file():
                    return str(Path(candidate).resolve())
            except OSError:
                continue
    return None

