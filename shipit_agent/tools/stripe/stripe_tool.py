"""The ``stripe`` tool: read Stripe customers, charges, subscriptions, invoices and products.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .http_helpers import _StripeHTTP
from .prompt import STRIPE_PROMPT
from .reads import _StripeReads
from .writes import _StripeWrites

_READ_ACTIONS = [
    "list_customers",
    "get_customer",
    "search_customers",
    "list_charges",
    "get_charge",
    "list_subscriptions",
    "get_subscription",
    "list_invoices",
    "get_invoice",
    "list_prices",
    "list_products",
]
_WRITE_ACTIONS = [
    "create_customer",
    "cancel_subscription",
]
_ACTIONS = _READ_ACTIONS + _WRITE_ACTIONS


class StripeTool(_StripeHTTP, _StripeReads, _StripeWrites, HTTPConnectorToolBase):
    """The ``stripe`` tool: read-heavy Stripe data: customers, charges, subscriptions, invoices, products.
    """
    provider = "stripe"

    def __init__(
        self,
        *,
        credential_key: str = "stripe",
        credential_store: Any = None,
        allow_writes: bool = False,
        name: str = "stripe",
        description: str = (
            "Read-heavy Stripe data: customers, charges, subscriptions, "
            "invoices, products. Writes gated by allow_writes."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = bool(allow_writes)
        self.name = name
        self.description = description
        self.prompt = prompt or STRIPE_PROMPT
        self.prompt_instructions = (
            "Use this for Stripe billing lookups: customers, charges, "
            "subscriptions, invoices, and catalog (products/prices). Writes "
            "are gated behind allow_writes=True."
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
                            "default": "list_customers",
                        },
                        "id": {
                            "type": "string",
                            "description": "Stripe resource id (cus_, ch_, sub_, in_, etc.)",
                        },
                        "customer": {
                            "type": "string",
                            "description": "Customer id filter (cus_...)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Stripe search DSL query for search_customers",
                        },
                        "email": {"type": "string"},
                        "name": {"type": "string"},
                        "status": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                        "starting_after": {"type": "string"},
                        "active": {"type": "boolean", "default": True},
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
        record = self._ensure_base_url(record)
        action = str(kwargs.get("action", "list_customers")).strip()

        handlers = {
            "list_customers": self._list_customers,
            "get_customer": self._get_customer,
            "search_customers": self._search_customers,
            "list_charges": self._list_charges,
            "get_charge": self._get_charge,
            "list_subscriptions": self._list_subscriptions,
            "get_subscription": self._get_subscription,
            "list_invoices": self._list_invoices,
            "get_invoice": self._get_invoice,
            "list_prices": self._list_prices,
            "list_products": self._list_products,
            "create_customer": self._create_customer,
            "cancel_subscription": self._cancel_subscription,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Stripe: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        if action in _WRITE_ACTIONS and not self.allow_writes:
            return self._write_blocked(action, record)
        return handler(record=record, action=action, kwargs=kwargs)
