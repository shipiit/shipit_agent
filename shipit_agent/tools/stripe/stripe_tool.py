from __future__ import annotations

import base64
import json
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import STRIPE_PROMPT


_DEFAULT_BASE_URL = "https://api.stripe.com"

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


class StripeTool(HTTPConnectorToolBase):
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

    # --------------------------------------------------------------- auth / URL

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.stripe.com."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get(
            "base_url"
        ):
            metadata["base_url"] = _DEFAULT_BASE_URL
        record.metadata = metadata
        return record

    def _api_key(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("api_key")
            or secrets.get("secret_key")
            or secrets.get("token")
            or ""
        )

    def _mode(self, record: CredentialRecord) -> str:
        key = self._api_key(record)
        return "test" if key.startswith("sk_test_") else "live"

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        # Stripe uses HTTP Basic auth with the secret key as username (no password).
        # Do NOT call super()._headers() — that would produce a Bearer header.
        key = self._api_key(record)
        headers: dict[str, str] = {}
        if key:
            token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
            headers["authorization"] = f"Basic {token}"
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    # ---------------------------------------------------------- form request

    def _request_form(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> Any:
        """POST/PATCH/DELETE with application/x-www-form-urlencoded body."""
        base_url = self._base_url(record)
        if not base_url:
            raise RuntimeError(
                f"{self.provider} credential record is missing base_url metadata."
            )
        url = f"{base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{parse.urlencode(query, doseq=True)}"
        data: bytes | None = None
        headers = self._headers(record)
        if form:
            filtered = {k: v for k, v in form.items() if v is not None}
            data = parse.urlencode(filtered, doseq=True).encode("utf-8")
            headers["content-type"] = "application/x-www-form-urlencoded"
        req = request.Request(
            url, data=data, headers=headers, method=method.upper()
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    # --------------------------------------------------------- error wrapper

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        try:
            if method.upper() == "GET":
                payload = self._request_json(
                    record=record, method=method, path=path, query=query
                )
            else:
                payload = self._request_form(
                    record=record,
                    method=method,
                    path=path,
                    query=query,
                    form=form,
                )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"Stripe request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        headers = getattr(err, "headers", None)
        if err.code == 429:
            retry_after = 0
            if headers is not None:
                try:
                    raw_retry = headers.get("Retry-After")
                    retry_after = int(raw_retry) if raw_retry is not None else 0
                except (TypeError, ValueError):
                    retry_after = 0
            return ToolOutput(
                text=(
                    "Stripe rate limit exceeded. "
                    f"Retry after {retry_after} seconds."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after": retry_after,
                    "status": 429,
                },
            )
        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"Stripe HTTP {err.code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": int(err.code),
                "message": message,
            },
        )

    @staticmethod
    def _extract_error_message(err: HTTPError) -> str:
        try:
            raw = err.read()
            if raw:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                err_obj = parsed.get("error")
                if isinstance(err_obj, dict):
                    msg = err_obj.get("message")
                    if isinstance(msg, str) and msg:
                        return msg
                top = parsed.get("message")
                if isinstance(top, str) and top:
                    return top
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    # --------------------------------------------------------------- helpers

    def _base_meta(self, record: CredentialRecord, action: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "connected": True,
            "action": action,
            "mode": self._mode(record),
        }

    def _write_blocked(self, action: str, record: CredentialRecord) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Stripe write '{action}' is disabled. Construct "
                "StripeTool(allow_writes=True) to enable destructive actions."
            ),
            metadata={
                **self._base_meta(record, action),
                "error": "writes_disabled",
            },
        )

    @staticmethod
    def _require_id(
        kwargs: dict[str, Any], action: str
    ) -> tuple[str, ToolOutput | None]:
        resource_id = str(kwargs.get("id", "")).strip()
        if not resource_id:
            return "", ToolOutput(
                text=f"Stripe: `id` is required for {action}.",
                metadata={
                    "provider": "stripe",
                    "error": "missing_parameter",
                    "missing": ["id"],
                },
            )
        return resource_id, None

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
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

    # ------------------------------------------------------------- actions

    def _list_query(self, kwargs: dict[str, Any], *extra_keys: str) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        if kwargs.get("starting_after"):
            query["starting_after"] = str(kwargs["starting_after"])
        for key in extra_keys:
            val = kwargs.get(key)
            if val is None or val == "":
                continue
            query[key] = val
        return query

    def _list_response(
        self,
        *,
        record: CredentialRecord,
        action: str,
        payload: Any,
        label: str,
        describe,
    ) -> ToolOutput:
        data = payload if isinstance(payload, dict) else {}
        items = data.get("data", []) or []
        lines = [describe(item) for item in items]
        text = "\n".join(lines) if lines else f"No Stripe {label} found."
        return ToolOutput(
            text=text,
            metadata={
                **self._base_meta(record, action),
                "items": items,
                "count": len(items),
                "has_more": bool(data.get("has_more")),
            },
        )

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
