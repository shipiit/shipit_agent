"""The ``salesforce`` tool: search Salesforce records; query SOQL/SOSL; read accounts/opportunities/contacts; log activities.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .http_helpers import _SalesforceHTTP
from .prompt import SALESFORCE_PROMPT
from .reads import _SalesforceReads
from .writes import _SalesforceWrites

_ACTIONS = [
    "search",
    "query",
    "get_record",
    "list_accounts",
    "list_opportunities",
    "list_contacts",
    "create_record",
    "update_record",
    "log_activity",
]


class SalesforceTool(
    _SalesforceHTTP,
    _SalesforceReads,
    _SalesforceWrites,
    HTTPConnectorToolBase,
):
    """The ``salesforce`` tool: search Salesforce records; query SOQL/SOSL; read accounts/opportunities/contacts; log activities.
    """
    provider = "salesforce"

    def __init__(
        self,
        *,
        credential_key: str = "salesforce",
        credential_store: Any = None,
        allow_writes: bool = False,
        api_version: str = "v60.0",
        name: str = "salesforce",
        description: str = (
            "Search Salesforce records; query SOQL/SOSL; read accounts/opportunities/"
            "contacts; log activities."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = bool(allow_writes)
        self.api_version = api_version.strip() or "v60.0"
        self.name = name
        self.description = description
        self.prompt = prompt or SALESFORCE_PROMPT
        self.prompt_instructions = (
            "Use this for Salesforce CRM lookups (accounts, opportunities, contacts), "
            "SOQL/SOSL queries, and activity logging. Writes are gated behind "
            "allow_writes; log_activity is always allowed."
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
                            "default": "query",
                        },
                        "query": {
                            "type": "string",
                            "description": "SOSL query string for the search action.",
                        },
                        "soql": {
                            "type": "string",
                            "description": "SOQL query string for the query action.",
                        },
                        "sobject": {
                            "type": "string",
                            "description": "Salesforce object API name (Account, Contact, ...).",
                        },
                        "record_id": {"type": "string"},
                        "fields": {
                            "type": "object",
                            "description": "Field name → value map for create/update.",
                        },
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "related_to_id": {
                            "type": "string",
                            "description": (
                                "Id of the Account / Opportunity / other record the "
                                "activity relates to (mapped to Task.WhatId)."
                            ),
                        },
                        "limit": {"type": "integer", "default": 50},
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
            return ToolOutput(
                text=(
                    "Salesforce credential record is missing the instance URL "
                    "(base_url)."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "missing_instance_url",
                    "hint": (
                        "Set base_url on the Salesforce CredentialRecord to your "
                        "org's instance URL, e.g. https://acme.my.salesforce.com"
                    ),
                },
            )

        action = str(kwargs.get("action", "")).strip()

        handlers = {
            "search": self._search,
            "query": self._query,
            "get_record": self._get_record_action,
            "list_accounts": self._list_accounts,
            "list_opportunities": self._list_opportunities,
            "list_contacts": self._list_contacts,
            "create_record": self._create_record,
            "update_record": self._update_record,
            "log_activity": self._log_activity,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Salesforce: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)
