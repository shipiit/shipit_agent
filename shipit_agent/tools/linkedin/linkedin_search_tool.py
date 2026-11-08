"""LinkedIn read-only lookup tool.

This tool is deliberately and verifiably read-only. It exposes profile and company
lookups plus discovery search, and nothing else. There is no action in the schema
that sends connection requests, InMails, messages, endorsements, or performs any
other write — the model literally cannot request one.

Users point it at LinkedIn's official API (Partner Program) or a third-party
enrichment vendor like Proxycurl or RapidAPI via the `base_url` metadata on the
credential record. Three auth shapes are supported:

* ``bearer`` (default) — ``Authorization: Bearer <token>``
* ``api_key_header`` — a custom header carrying the token (e.g. ``X-RapidAPI-Key``)
* ``query_param`` — the token is appended as ``?api_key=<token>`` on every request

Writes / automation / scraping are explicitly out of scope so the tool stays on
the right side of LinkedIn's Terms of Service.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .http_helpers import _LinkedInHTTP
from .lookups import _LookupActions
from .prompt import LINKEDIN_SEARCH_PROMPT

# READ-ONLY actions only. No write / messaging / connection action is permitted.
_ACTIONS: tuple[str, ...] = (
    "lookup_profile",
    "lookup_company",
    "search_people",
    "search_companies",
    "list_company_employees",
)


class LinkedInSearchTool(_LinkedInHTTP, _LookupActions, HTTPConnectorToolBase):
    """Read-only LinkedIn lookup.

    No messaging, connection requests, endorsements, or other automation.
    This is a deliberate product boundary to keep agents compliant with
    LinkedIn's Terms of Service.
    """

    provider = "linkedin"

    def __init__(
        self,
        *,
        credential_key: str = "linkedin",
        credential_store: Any = None,
        name: str = "linkedin_search",
        description: str = (
            "Read-only LinkedIn lookup: profiles, companies, employee search. "
            "NO messaging, connection requests, or automation — this tool is "
            "intentionally read-only to keep agents compliant with LinkedIn ToS."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or LINKEDIN_SEARCH_PROMPT
        self.prompt_instructions = (
            "Use this for read-only LinkedIn lookups: profiles, companies, and "
            "public people/company search. This tool cannot send messages, "
            "connection requests, or any other write action."
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
                            "default": "lookup_profile",
                        },
                        "profile_url": {"type": "string"},
                        "username": {"type": "string"},
                        "company_url": {"type": "string"},
                        "slug": {"type": "string"},
                        "query": {"type": "string"},
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "industry": {"type": "string"},
                        "size": {"type": "string"},
                        "limit": {"type": "integer", "default": 25},
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
        if not self._base_url(record):
            return self._missing_base_url_output()

        action = str(kwargs.get("action", "")).strip()

        handlers = {
            "lookup_profile": self._lookup_profile,
            "lookup_company": self._lookup_company,
            "search_people": self._search_people,
            "search_companies": self._search_companies,
            "list_company_employees": self._list_company_employees,
        }
        # Enforce read-only invariant defensively: if the action somehow carries
        # a write-flavored name, reject it before dispatch.
        if any(
            token in action.lower()
            for token in (
                "send",
                "message",
                "connect",
                "invite",
                "endorse",
                "follow",
                "post",
                "create",
                "update",
                "delete",
            )
        ):
            return ToolOutput(
                text=(
                    f"LinkedIn: action '{action}' is not permitted. This tool is "
                    "read-only and does not support messaging, connection, or any "
                    "write action."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "write_action_blocked",
                    "action": action,
                },
            )

        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"LinkedIn: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                    "allowed": list(_ACTIONS),
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)
