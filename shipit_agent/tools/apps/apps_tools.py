"""The app tools — build something once, then use it.

Four tools, mirroring what Cloudflare OS gives its agent for gadgets:

- ``list_blueprints``  — what can I start from?
- ``create_app``       — write one into the workspace
- ``set_app_binding``  — wire a resource into it
- ``use_app``          — run it, with input, and get its answer back

The split matters. Creating and using are different acts with different
risks: creation writes files (revertible), use runs code (not deferrable —
the agent reads the result). Wiring changes what an app is *allowed to reach*,
which is a decision that belongs in the transcript rather than buried in a
code string.

See :mod:`shipit_agent.apps` for what an app is and how its `env` is gated.
"""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.apps import (
    AppStore,
    app_docstring,
    blueprint_catalogue,
    run_app,
)
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.describe_binding.describe_binding_tool import (
    BINDINGS_STATE_KEY,
)
from shipit_agent.tools.execute_code.execute_code_tool import INVOKER_STATE_KEY
from shipit_agent.tools.formatting import clip_text

__all__ = [
    "CreateAppTool",
    "ListBlueprintsTool",
    "SetAppBindingTool",
    "UseAppTool",
    "app_tools",
]

_MAX_OUTPUT = 12_000

APPS_PROMPT = """
When a task will be asked again — a weekly report, an intake step, a check you
run every release — build an app instead of redoing the work. `create_app`
writes it, `set_app_binding` wires a resource into it, and `use_app` runs it
with input and hands you the result.

An app is a directory with `app.py` exporting `run(input, env)`. It runs in a
subprocess: `env` holds only the bindings you wired, and every call on them is
gated exactly like the equivalent tool call.

Start from `list_blueprints` when one fits; write `app.py` yourself when none
does.
""".strip()


class _AppTool:
    """Shared plumbing: one store, one description of where apps live."""

    def __init__(self, store: AppStore) -> None:
        self.store = store
        self.prompt_instructions = ""

    @staticmethod
    def _function(name: str, description: str, properties: dict, required: list):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ListBlueprintsTool(_AppTool):
    """What the agent can start an app from."""

    name = "list_blueprints"
    read_only = True
    description = "List the app blueprints available to start a new app from."

    def schema(self) -> dict[str, Any]:
        return self._function(self.name, self.description, {}, [])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        existing = self.store.list()
        text = ["Blueprints:", blueprint_catalogue()]
        if existing:
            text += [
                "",
                "Apps that already exist:",
                *(f"- `{app.name}` — {app.manifest.title}" for app in existing),
            ]
        return ToolOutput(
            text="\n".join(text),
            metadata={"blueprints": True, "apps": [a.name for a in existing]},
        )


class CreateAppTool(_AppTool):
    """Write a new app into the workspace."""

    name = "create_app"
    read_only = False
    description = (
        "Create an app: a small program saved in the workspace that can be run "
        "again later with use_app. Start from a blueprint or supply app.py."
    )

    def __init__(self, store: AppStore) -> None:
        super().__init__(store)
        self.prompt_instructions = APPS_PROMPT

    def schema(self) -> dict[str, Any]:
        return self._function(
            self.name,
            self.description,
            {
                "name": {
                    "type": "string",
                    "description": (
                        "Lower snake case. Also the name it is bound under."
                    ),
                },
                "title": {"type": "string", "description": "Human-readable title."},
                "description": {
                    "type": "string",
                    "description": "One line on what the app does.",
                },
                "blueprint": {
                    "type": "string",
                    "description": "Blueprint id from list_blueprints, optional.",
                },
                "code": {
                    "type": "string",
                    "description": (
                        "The app's app.py, defining run(input, env). Required "
                        "unless a blueprint supplies it; overrides the "
                        "blueprint's own app.py when both are given."
                    ),
                },
            },
            ["name", "title"],
        )

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        name = str(kwargs.get("name") or "")
        code = kwargs.get("code")
        files = {"app.py": str(code)} if code else None
        try:
            app = self.store.create(
                name,
                title=str(kwargs.get("title") or name),
                description=str(kwargs.get("description") or ""),
                files=files,
                blueprint=kwargs.get("blueprint"),
                overwrite=bool(kwargs.get("overwrite")),
            )
        except (ValueError, KeyError, FileExistsError) as exc:
            return ToolOutput(text=str(exc), metadata={"error": "create_failed"})

        note = ""
        blueprint = kwargs.get("blueprint")
        if blueprint:
            from shipit_agent.apps import BLUEPRINTS

            note = "\n" + BLUEPRINTS[blueprint].notes()
        return ToolOutput(
            text=f"Created `{app.name}` at {app.path}.{note}\n\n{app.describe()}",
            metadata={"app": app.name, "path": str(app.path),
                      "blueprint": blueprint},
        )


class SetAppBindingTool(_AppTool):
    """Wire one of the agent's bindings into an app's own env."""

    name = "set_app_binding"
    read_only = False
    description = (
        "Wire one of your resource bindings into an app, so the app can use it. "
        "An app only ever sees what you wire into it."
    )

    def schema(self) -> dict[str, Any]:
        return self._function(
            self.name,
            self.description,
            {
                "app": {"type": "string", "description": "The app's name."},
                "source": {
                    "type": "string",
                    "description": "Binding name in your env, e.g. SHEETS.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Name it takes inside the app; defaults to `source`."
                    ),
                },
            },
            ["app", "source"],
        )

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        source = str(kwargs.get("source") or "")
        available = context.state.get(BINDINGS_STATE_KEY) or {}
        if available and source not in available:
            return ToolOutput(
                text=(
                    f"No binding named {source!r}. Available: "
                    f"{', '.join(sorted(available)) or 'none'}."
                ),
                metadata={"error": "unknown_binding"},
            )
        try:
            app = self.store.bind(
                str(kwargs.get("app") or ""),
                source=source,
                as_name=kwargs.get("name"),
            )
        except (KeyError, ValueError) as exc:
            return ToolOutput(text=str(exc), metadata={"error": "bind_failed"})
        return ToolOutput(
            text=f"Wired {source} into `{app.name}`.\n\n{app.describe()}",
            metadata={"app": app.name, "binding": source},
        )


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

        return ToolOutput(
            text=clip_text("\n\n".join(parts), max_chars=_MAX_OUTPUT),
            metadata={
                "app": app.name,
                "ok": result.ok,
                "env_calls": result.env_calls,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "value": result.value,
            },
        )


def app_tools(
    store: AppStore | str | None = None,
    *,
    timeout_seconds: float = 60.0,
    workdir: str | None = None,
) -> list[Any]:
    """The four app tools, sharing one store::

        agent = Agent(llm=llm, tools=[*app_tools(".shipit/apps"), *readers])
    """
    if store is None or isinstance(store, str):
        store = AppStore(store or ".shipit/apps", workdir=workdir)
    return [
        ListBlueprintsTool(store),
        CreateAppTool(store),
        SetAppBindingTool(store),
        UseAppTool(store, timeout_seconds=timeout_seconds),
    ]
