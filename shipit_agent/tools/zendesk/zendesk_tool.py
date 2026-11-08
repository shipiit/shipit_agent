"""The ``zendesk`` tool: search / read / comment on Zendesk tickets and users; list and preview macros.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .http_helpers import _ZendeskHTTP
from .prompt import ZENDESK_PROMPT
from .ticket_reads import _TicketReads
from .ticket_writes import _TicketWrites
from .users_macros import _UserMacroActions

_ACTIONS = [
    "search_tickets",
    "get_ticket",
    "create_ticket",
    "update_ticket",
    "add_comment",
    "close_ticket",
    "list_tickets",
    "get_user",
    "search_users",
    "list_macros",
    "apply_macro",
]

_WRITE_GATED_ACTIONS = {"create_ticket", "update_ticket", "close_ticket"}


class ZendeskTool(
    _ZendeskHTTP,
    _TicketReads,
    _TicketWrites,
    _UserMacroActions,
    HTTPConnectorToolBase,
):
    """The ``zendesk`` tool: search / read / comment on Zendesk tickets and users; list and preview macros.
    """
    provider = "zendesk"

    def __init__(
        self,
        *,
        credential_key: str = "zendesk",
        credential_store: Any = None,
        allow_writes: bool = False,
        name: str = "zendesk",
        description: str = (
            "Search / read / comment on Zendesk tickets and users; list and "
            "preview macros."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = allow_writes
        self.name = name
        self.description = description
        self.prompt = prompt or ZENDESK_PROMPT
        self.prompt_instructions = (
            "Use this for Zendesk ticket triage, customer support lookups, "
            "adding comments, and previewing macros."
        )

    # ------------------------------------------------------------------ schema

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
                            "enum": list(_ACTIONS),
                            "default": "search_tickets",
                        },
                        "id": {"type": "integer"},
                        "macro_id": {"type": "integer"},
                        "query": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "requester_email": {"type": "string"},
                        "priority": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "fields": {
                            "type": "object",
                            "description": (
                                "Arbitrary ticket fields for update_ticket "
                                "(merged into the nested `ticket` body)."
                            ),
                        },
                        "public": {"type": "boolean", "default": True},
                        "per_page": {"type": "integer", "default": 100},
                        "page": {"type": "integer", "default": 1},
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)

        action = str(kwargs.get("action", "search_tickets")).strip()

        if action in _WRITE_GATED_ACTIONS and not self.allow_writes:
            return self._writes_disabled_output(action)

        if not self._base_url(record):
            return self._missing_subdomain_output()

        handlers = {
            "search_tickets": self._search_tickets,
            "get_ticket": self._get_ticket,
            "create_ticket": self._create_ticket,
            "update_ticket": self._update_ticket,
            "add_comment": self._add_comment,
            "close_ticket": self._close_ticket,
            "list_tickets": self._list_tickets,
            "get_user": self._get_user,
            "search_users": self._search_users,
            "list_macros": self._list_macros,
            "apply_macro": self._apply_macro,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Zendesk: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)
