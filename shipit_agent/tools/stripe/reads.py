"""Stripe read actions: customers, charges, subscriptions, invoices, prices, products."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _StripeReads:
    """Stripe read actions: customers, charges, subscriptions, invoices, prices, products."""

    def _list_customers(self, *, record, action, kwargs):
        query = self._list_query(kwargs)
        payload, err = self._request_or_error(
            record=record, method="GET", path="/v1/customers", query=query or None
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="customers",
            describe=lambda c: (
                f"{c.get('id', '?')}  {c.get('email', '')}  {c.get('name', '')}"
            ).strip(),
        )

    def _get_customer(self, *, record, action, kwargs):
        resource_id, err = self._require_id(kwargs, action)
        if err is not None:
            return err
        payload, err = self._request_or_error(
            record=record, method="GET", path=f"/v1/customers/{resource_id}"
        )
        if err is not None:
            return err
        cust = payload if isinstance(payload, dict) else {}
        text = (
            f"{cust.get('id', resource_id)}  {cust.get('email', '')}  "
            f"{cust.get('name', '')}".strip()
        )
        return ToolOutput(
            text=text,
            metadata={**self._base_meta(record, action), "item": cust},
        )

    def _search_customers(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="Stripe: `query` is required for search_customers.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["query"],
                },
            )
        query: dict[str, Any] = {"query": q}
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/v1/customers/search",
            query=query,
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="customers",
            describe=lambda c: (
                f"{c.get('id', '?')}  {c.get('email', '')}  {c.get('name', '')}"
            ).strip(),
        )

    def _list_charges(self, *, record, action, kwargs):
        query = self._list_query(kwargs, "customer")
        payload, err = self._request_or_error(
            record=record, method="GET", path="/v1/charges", query=query or None
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="charges",
            describe=lambda c: (
                f"{c.get('id', '?')}  {c.get('amount', 0)} "
                f"{str(c.get('currency', '')).upper()}  "
                f"{c.get('status', '?')}"
            ),
        )

    def _get_charge(self, *, record, action, kwargs):
        resource_id, err = self._require_id(kwargs, action)
        if err is not None:
            return err
        payload, err = self._request_or_error(
            record=record, method="GET", path=f"/v1/charges/{resource_id}"
        )
        if err is not None:
            return err
        charge = payload if isinstance(payload, dict) else {}
        text = (
            f"{charge.get('id', resource_id)}  {charge.get('amount', 0)} "
            f"{str(charge.get('currency', '')).upper()}  "
            f"{charge.get('status', '?')}"
        )
        return ToolOutput(
            text=text,
            metadata={**self._base_meta(record, action), "item": charge},
        )

    def _list_subscriptions(self, *, record, action, kwargs):
        query = self._list_query(kwargs, "customer", "status")
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/v1/subscriptions",
            query=query or None,
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="subscriptions",
            describe=lambda s: (
                f"{s.get('id', '?')}  {s.get('status', '?')}  "
                f"customer={s.get('customer', '?')}"
            ),
        )

    def _get_subscription(self, *, record, action, kwargs):
        resource_id, err = self._require_id(kwargs, action)
        if err is not None:
            return err
        payload, err = self._request_or_error(
            record=record, method="GET", path=f"/v1/subscriptions/{resource_id}"
        )
        if err is not None:
            return err
        sub = payload if isinstance(payload, dict) else {}
        text = (
            f"{sub.get('id', resource_id)}  {sub.get('status', '?')}  "
            f"customer={sub.get('customer', '?')}"
        )
        return ToolOutput(
            text=text,
            metadata={**self._base_meta(record, action), "item": sub},
        )

    def _list_invoices(self, *, record, action, kwargs):
        query = self._list_query(kwargs, "customer", "status")
        payload, err = self._request_or_error(
            record=record, method="GET", path="/v1/invoices", query=query or None
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="invoices",
            describe=lambda i: (
                f"{i.get('id', '?')}  {i.get('status', '?')}  "
                f"{i.get('amount_due', 0)} "
                f"{str(i.get('currency', '')).upper()}"
            ),
        )

    def _get_invoice(self, *, record, action, kwargs):
        resource_id, err = self._require_id(kwargs, action)
        if err is not None:
            return err
        payload, err = self._request_or_error(
            record=record, method="GET", path=f"/v1/invoices/{resource_id}"
        )
        if err is not None:
            return err
        inv = payload if isinstance(payload, dict) else {}
        text = (
            f"{inv.get('id', resource_id)}  {inv.get('status', '?')}  "
            f"{inv.get('amount_due', 0)} "
            f"{str(inv.get('currency', '')).upper()}"
        )
        return ToolOutput(
            text=text,
            metadata={**self._base_meta(record, action), "item": inv},
        )

    def _list_prices(self, *, record, action, kwargs):
        query = self._list_query(kwargs)
        active = kwargs.get("active")
        if active is None:
            active = True
        query["active"] = "true" if bool(active) else "false"
        payload, err = self._request_or_error(
            record=record, method="GET", path="/v1/prices", query=query or None
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="prices",
            describe=lambda p: (
                f"{p.get('id', '?')}  {p.get('unit_amount', 0)} "
                f"{str(p.get('currency', '')).upper()}  "
                f"product={p.get('product', '?')}"
            ),
        )

    def _list_products(self, *, record, action, kwargs):
        query = self._list_query(kwargs)
        active = kwargs.get("active")
        if active is None:
            active = True
        query["active"] = "true" if bool(active) else "false"
        payload, err = self._request_or_error(
            record=record, method="GET", path="/v1/products", query=query or None
        )
        if err is not None:
            return err
        return self._list_response(
            record=record,
            action=action,
            payload=payload,
            label="products",
            describe=lambda p: (
                f"{p.get('id', '?')}  {p.get('name', '')}  "
                f"active={p.get('active', '?')}"
            ),
        )
