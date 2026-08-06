"""``connections`` — see what is connected, and ask for what is not.

Before this, a connector with no credential failed *mid-task*: the agent
called `slack`, got back a string saying it was not connected, and had to
work out what that meant. It could not check first, and it could not ask.

Two operations, matching Cloudflare OS's `listConnectableResources` and
`requestConnection`:

- **list** — what is connected, what needs authenticating, what is missing
- **request** — record that a connection is needed, with a reason

Requesting is deliberately not an error. A missing connection is something the
*user* resolves, so it belongs in the transcript as a request with a reason,
not as a stack trace the model tries to route around.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

# The runtime publishes the resolved registry here.
REGISTRY_STATE_KEY = "connection_registry"

CONNECTIONS_PROMPT = """
Check `connections` before using a connector for the first time in a task, and
whenever a connector call fails for want of credentials.

If something you need is not connected, call this with action="request" and a
reason. That surfaces it to the user as a decision. Do not keep retrying the
connector, and do not invent an alternative route to the same data.
""".strip()


class ConnectionsTool:
    """List connections, or request one."""

    read_only = True

    def __init__(self, *, name: str = "connections") -> None:
        self.name = name
        self.description = (
            "List which external services are connected and which need "
            "authenticating, or request a connection you need."
        )
        self.prompt_instructions = CONNECTIONS_PROMPT

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "check", "request"],
                            "description": (
                                "'list' shows everything; 'check' reports one "
                                "connection; 'request' asks the user to "
                                "connect one."
                            ),
                            "default": "list",
                        },
                        "connection": {
                            "type": "string",
                            "description": (
                                "Which connection, for 'check' and 'request' "
                                "— e.g. 'slack', 'github'."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "For 'request': why you need it, in one line. "
                                "The user reads this to decide."
                            ),
                        },
                        "connected_only": {
                            "type": "boolean",
                            "description": "For 'list': hide what isn't connected.",
                            "default": False,
                        },
                    },
                    "required": [],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        registry = (getattr(context, "state", None) or {}).get(REGISTRY_STATE_KEY)
        if registry is None:
            return ToolOutput(
                text=(
                    "Connection information is not available in this run."
                ),
                metadata={"ok": False, "error": "no_registry"},
            )

        action = str(kwargs.get("action") or "list").strip().lower()
        if action == "request":
            return self._request(registry, kwargs)
        if action == "check":
            return self._check(registry, kwargs)
        return self._list(registry, kwargs)

    def _list(self, registry: Any, kwargs: dict[str, Any]) -> ToolOutput:
        only_connected = bool(kwargs.get("connected_only"))
        return ToolOutput(
            text=registry.render(only_connected=only_connected),
            metadata={
                **registry.summary(),
                "connections": [c.to_dict() for c in registry.all()],
            },
        )

    def _check(self, registry: Any, kwargs: dict[str, Any]) -> ToolOutput:
        wanted = str(kwargs.get("connection") or "").strip()
        if not wanted:
            return ToolOutput(
                text="Which connection? Pass `connection`.",
                metadata={"ok": False},
            )
        connection = registry.get(wanted)
        if connection is None:
            known = ", ".join(sorted(c.id for c in registry.all())) or "none"
            return ToolOutput(
                text=f"No connection named {wanted!r}. Known: {known}.",
                metadata={"ok": False, "connection": wanted},
            )
        text = connection.describe()
        if connection.needs_action:
            text += f"\n→ {connection.next_step()}"
        return ToolOutput(text=text, metadata=connection.to_dict())

    def _request(self, registry: Any, kwargs: dict[str, Any]) -> ToolOutput:
        wanted = str(kwargs.get("connection") or "").strip()
        reason = str(kwargs.get("reason") or "").strip()
        if not wanted:
            return ToolOutput(
                text="Which connection? Pass `connection`.",
                metadata={"ok": False},
            )
        if not reason:
            # A request with no reason is one the user cannot evaluate.
            return ToolOutput(
                text=(
                    "Say why you need it — the user reads the reason to "
                    "decide whether to connect."
                ),
                metadata={"ok": False, "error": "missing_reason"},
            )

        existing = registry.get(wanted)
        if existing is not None and existing.usable:
            return ToolOutput(
                text=f"{existing.title} is already connected — go ahead.",
                metadata={**existing.to_dict(), "already_connected": True},
            )

        request = registry.request(wanted, reason)
        step = existing.next_step() if existing else f"Connect {wanted}."
        return ToolOutput(
            text=(
                f"Requested: {request.title}. {reason}\n→ {step}\n"
                f"Continue with anything that does not need it; do not retry "
                f"the connector until it is connected."
            ),
            metadata={**request.to_dict(), "requested": True},
        )
