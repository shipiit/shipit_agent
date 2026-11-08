"""Stripe write actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _StripeWrites:
    """Stripe write actions."""

    def _create_customer(self, *, record, action, kwargs):
        email = str(kwargs.get("email", "")).strip()
        name = str(kwargs.get("name", "")).strip()
        if not email and not name:
            return ToolOutput(
                text="Stripe: create_customer requires `email` or `name`.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["email", "name"],
                },
            )
        form: dict[str, Any] = {}
        if email:
            form["email"] = email
        if name:
            form["name"] = name
        payload, err = self._request_or_error(
            record=record, method="POST", path="/v1/customers", form=form
        )
        if err is not None:
            return err
        cust = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Stripe customer created: {cust.get('id', '?')} "
                f"{cust.get('email', '')} {cust.get('name', '')}"
            ).strip(),
            metadata={**self._base_meta(record, action), "item": cust},
        )

    def _cancel_subscription(self, *, record, action, kwargs):
        resource_id, err = self._require_id(kwargs, action)
        if err is not None:
            return err
        payload, err = self._request_or_error(
            record=record,
            method="DELETE",
            path=f"/v1/subscriptions/{resource_id}",
        )
        if err is not None:
            return err
        sub = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Stripe subscription cancelled: {sub.get('id', resource_id)} "
                f"({sub.get('status', 'canceled')})"
            ),
            metadata={**self._base_meta(record, action), "item": sub},
        )
