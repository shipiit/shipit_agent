from __future__ import annotations

import base64
import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.stripe import STRIPE_PROMPT, StripeTool


# ---------------------------------------------------------------- helpers

def _store(key: str = "sk_test_demo", *, include_base_url: bool = True):
    s = InMemoryCredentialStore()
    metadata: dict = {}
    if include_base_url:
        metadata["base_url"] = "https://api.stripe.com"
    s.set(
        CredentialRecord(
            key="stripe",
            provider="stripe",
            secrets={"api_key": key},
            metadata=metadata,
        )
    )
    return s


def _ctx(store=None):
    state = {}
    if store is not None:
        state["credential_store"] = store
    return ToolContext(prompt="test", state=state)


def _capture_json(payload):
    """Fake `_request_json` (used for GET)."""
    captured: list[dict] = []

    def fake(*, record, method, path, query=None, body=None):
        captured.append(
            {
                "record": record,
                "method": method,
                "path": path,
                "query": query,
                "body": body,
            }
        )
        return payload

    return captured, fake


def _capture_form(payload):
    """Fake `_request_form` (used for POST/DELETE)."""
    captured: list[dict] = []

    def fake(*, record, method, path, query=None, form=None):
        captured.append(
            {
                "record": record,
                "method": method,
                "path": path,
                "query": query,
                "form": form,
            }
        )
        return payload

    return captured, fake


def _http_error(code: int, body: bytes = b"", headers: dict | None = None):
    return HTTPError(
        url="https://api.stripe.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata

def test_tool_name_description_and_prompt():
    tool = StripeTool()
    assert tool.name == "stripe"
    assert tool.provider == "stripe"
    assert "Stripe" in tool.description
    assert STRIPE_PROMPT in tool.prompt


def test_schema_contains_full_action_enum():
    enum = (
        StripeTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
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
        "create_customer",
        "cancel_subscription",
    } == set(enum)


def test_unknown_action_returns_structured_error():
    tool = StripeTool(credential_store=_store())
    out = tool.run(context=_ctx(_store()), action="nope")
    assert out.metadata["error"] == "unsupported_action"
    assert "unsupported action" in out.text.lower()


def test_not_connected_when_no_store():
    tool = StripeTool()
    out = tool.run(context=ToolContext(prompt="x"), action="list_customers")
    assert out.metadata["connected"] is False
    assert "not connected" in out.text.lower()


# ---------------------------------------------------------------- auth / URL

def test_basic_auth_header_is_base64_of_key_colon():
    tool = StripeTool(credential_store=_store(key="sk_test_xxx"))
    record = _store(key="sk_test_xxx").get("stripe")
    headers = tool._headers(record)
    expected = "Basic " + base64.b64encode(b"sk_test_xxx:").decode("ascii")
    assert headers["authorization"] == expected
    # No content-type for bare GET — form handler adds it itself.
    assert "content-type" not in {k.lower() for k in headers}


def test_default_base_url_fallback_when_missing():
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="stripe",
            provider="stripe",
            secrets={"api_key": "sk_test_demo"},
            metadata={},
        )
    )
    tool = StripeTool(credential_store=store)
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(store), action="list_customers")
    rec = store.get("stripe")
    assert rec.metadata["base_url"] == "https://api.stripe.com"


def test_mode_detection_test_key():
    tool = StripeTool(credential_store=_store(key="sk_test_abc"))
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store(key="sk_test_abc")), action="list_customers")
    assert out.metadata["mode"] == "test"


def test_mode_detection_live_key():
    tool = StripeTool(credential_store=_store(key="sk_live_abc"))
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store(key="sk_live_abc")), action="list_customers")
    assert out.metadata["mode"] == "live"


# ---------------------------------------------------------------- customers

def test_list_customers_sends_limit_and_cursor():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json(
        {
            "data": [
                {"id": "cus_1", "email": "a@x", "name": "Alice"},
                {"id": "cus_2", "email": "b@x", "name": "Bob"},
            ],
            "has_more": True,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_customers",
        limit=5,
        starting_after="cus_0",
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/v1/customers"
    assert call["query"] == {"limit": 5, "starting_after": "cus_0"}
    assert out.metadata["count"] == 2
    assert out.metadata["has_more"] is True
    assert "cus_1" in out.text


def test_get_customer():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json({"id": "cus_1", "email": "a@x", "name": "Alice"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()), action="get_customer", id="cus_1"
    )
    assert captured[0]["path"] == "/v1/customers/cus_1"
    assert "cus_1" in out.text
    assert "Alice" in out.text


def test_search_customers_sends_query_dsl():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(_store()),
        action="search_customers",
        query="email:'alice@acme.com'",
        limit=3,
    )
    call = captured[0]
    assert call["path"] == "/v1/customers/search"
    assert call["query"] == {"query": "email:'alice@acme.com'", "limit": 3}


# ---------------------------------------------------------------- charges

def test_list_charges_with_customer_filter():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json(
        {
            "data": [
                {"id": "ch_1", "amount": 1000, "currency": "usd", "status": "succeeded"}
            ],
            "has_more": False,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_charges",
        customer="cus_1",
        limit=10,
    )
    call = captured[0]
    assert call["path"] == "/v1/charges"
    assert call["query"] == {"limit": 10, "customer": "cus_1"}
    assert "ch_1" in out.text
    assert "USD" in out.text


def test_get_charge():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json(
        {"id": "ch_1", "amount": 500, "currency": "usd", "status": "succeeded"}
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_charge", id="ch_1")
    assert captured[0]["path"] == "/v1/charges/ch_1"
    assert "succeeded" in out.text


# ---------------------------------------------------------------- subs

def test_list_subscriptions_with_status_filter():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json(
        {
            "data": [
                {"id": "sub_1", "status": "active", "customer": "cus_1"}
            ],
            "has_more": False,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_subscriptions",
        customer="cus_1",
        status="active",
        limit=20,
    )
    call = captured[0]
    assert call["path"] == "/v1/subscriptions"
    assert call["query"] == {
        "limit": 20,
        "customer": "cus_1",
        "status": "active",
    }
    assert "sub_1" in out.text


# ---------------------------------------------------------------- invoices / catalog

def test_list_invoices_with_filters():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(_store()),
        action="list_invoices",
        customer="cus_1",
        status="open",
        limit=15,
    )
    call = captured[0]
    assert call["path"] == "/v1/invoices"
    assert call["query"] == {
        "limit": 15,
        "customer": "cus_1",
        "status": "open",
    }


def test_get_invoice():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json(
        {"id": "in_1", "status": "paid", "amount_due": 0, "currency": "usd"}
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_invoice", id="in_1")
    assert captured[0]["path"] == "/v1/invoices/in_1"
    assert "paid" in out.text


def test_list_prices_defaults_active_true():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="list_prices", limit=25)
    call = captured[0]
    assert call["path"] == "/v1/prices"
    assert call["query"]["active"] == "true"
    assert call["query"]["limit"] == 25


def test_list_products_defaults_active_true():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_json({"data": [], "has_more": False})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="list_products")
    call = captured[0]
    assert call["path"] == "/v1/products"
    assert call["query"]["active"] == "true"


# ---------------------------------------------------------------- writes

def test_create_customer_rejected_without_allow_writes():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_form({"id": "cus_new"})
    tool._request_form = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_customer",
        email="alice@acme.com",
        name="Alice",
    )
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []


def test_cancel_subscription_rejected_without_allow_writes():
    tool = StripeTool(credential_store=_store())
    captured, fake = _capture_form({"id": "sub_1", "status": "canceled"})
    tool._request_form = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()), action="cancel_subscription", id="sub_1"
    )
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []


def test_create_customer_post_body_is_form_urlencoded(monkeypatch):
    tool = StripeTool(credential_store=_store(), allow_writes=True)
    captured_url: dict = {}

    class FakeResp:
        def __init__(self, raw: bytes):
            self._raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._raw

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured_url["url"] = req.full_url
        captured_url["method"] = req.get_method()
        captured_url["headers"] = dict(req.header_items())
        captured_url["data"] = req.data
        return FakeResp(b'{"id":"cus_new","email":"alice@acme.com","name":"Alice"}')

    monkeypatch.setattr(
        "shipit_agent.tools.stripe.stripe_tool.request.urlopen", fake_urlopen
    )
    out = tool.run(
        context=_ctx(_store()),
        action="create_customer",
        email="alice@acme.com",
        name="Alice",
    )
    assert captured_url["method"] == "POST"
    assert captured_url["url"] == "https://api.stripe.com/v1/customers"
    # Body is form-urlencoded, not JSON.
    body = captured_url["data"].decode("utf-8")
    assert "email=alice%40acme.com" in body
    assert "name=Alice" in body
    # content-type header is form-urlencoded (header keys casefolded by urllib).
    ct = {k.lower(): v for k, v in captured_url["headers"].items()}.get(
        "content-type", ""
    )
    assert ct == "application/x-www-form-urlencoded"
    # Basic auth header propagated.
    auth = {k.lower(): v for k, v in captured_url["headers"].items()}.get(
        "authorization", ""
    )
    assert auth.startswith("Basic ")
    assert out.metadata["item"]["id"] == "cus_new"


def test_cancel_subscription_uses_delete_path(monkeypatch):
    tool = StripeTool(credential_store=_store(), allow_writes=True)
    captured: dict = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id":"sub_1","status":"canceled"}'

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return FakeResp()

    monkeypatch.setattr(
        "shipit_agent.tools.stripe.stripe_tool.request.urlopen", fake_urlopen
    )
    out = tool.run(
        context=_ctx(_store()), action="cancel_subscription", id="sub_1"
    )
    assert captured["method"] == "DELETE"
    assert captured["url"] == "https://api.stripe.com/v1/subscriptions/sub_1"
    assert "cancelled" in out.text.lower() or "canceled" in out.text.lower()


# ---------------------------------------------------------------- errors

def test_rate_limit_429_returns_retry_after():
    tool = StripeTool(credential_store=_store())

    def raise_429(**_kwargs):
        raise _http_error(
            429,
            body=b'{"error":{"message":"Too many requests"}}',
            headers={"Retry-After": "7"},
        )

    tool._request_json = raise_429  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="list_customers")
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after"] == 7
    assert out.metadata["status"] == 429


def test_stripe_error_json_shape_yields_inner_message():
    tool = StripeTool(credential_store=_store())

    def raise_402(**_kwargs):
        raise _http_error(
            402,
            body=b'{"error":{"message":"Your card was declined."}}',
            headers={},
        )

    tool._request_json = raise_402  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_charge", id="ch_bad")
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 402
    assert out.metadata["message"] == "Your card was declined."
    assert "402" in out.text


# reference imports so linters keep them
assert pytest is not None
