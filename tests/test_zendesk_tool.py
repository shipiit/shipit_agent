from __future__ import annotations

import base64
import io
import re
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.zendesk import ZENDESK_PROMPT, ZendeskTool


# ---------------------------------------------------------------- helpers

def _store(email="alice@acme.com", token="demo123", subdomain="acme"):
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="zendesk",
            provider="zendesk",
            secrets={"email": email, "api_token": token},
            metadata={"base_url": f"https://{subdomain}.zendesk.com"},
        )
    )
    return s


def _store_no_subdomain():
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="zendesk",
            provider="zendesk",
            secrets={"email": "alice@acme.com", "api_token": "demo123"},
            metadata={},
        )
    )
    return s


def _ctx(store=None):
    state = {}
    if store is not None:
        state["credential_store"] = store
    return ToolContext(prompt="test", state=state)


def _capture(payload):
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


def _http_error(code, body=b'{"error":"Err","description":"Boom"}', headers=None):
    return HTTPError(
        url="https://acme.zendesk.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# --------------------------------------------------------------- metadata

def test_tool_shape_and_prompt():
    tool = ZendeskTool()
    assert tool.name == "zendesk"
    assert tool.provider == "zendesk"
    assert "Zendesk" in tool.description
    assert ZENDESK_PROMPT in tool.prompt
    assert tool.allow_writes is False


def test_schema_enum_contains_all_actions():
    actions = (
        ZendeskTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
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
    } == set(actions)


def test_unknown_action_returns_structured_error():
    tool = ZendeskTool(credential_store=_store())
    result = tool.run(context=_ctx(_store()), action="nope")
    assert result.metadata["error"] == "unsupported_action"
    assert "unsupported action" in result.text.lower()


def test_not_connected_when_no_store():
    tool = ZendeskTool()
    out = tool.run(context=ToolContext(prompt="x"), action="search_tickets")
    assert out.metadata["connected"] is False
    assert "not connected" in out.text.lower()


def test_missing_subdomain_surfaces_hint():
    tool = ZendeskTool(credential_store=_store_no_subdomain())
    out = tool.run(
        context=_ctx(_store_no_subdomain()),
        action="search_tickets",
        query="status:open",
    )
    assert out.metadata["error"] == "missing_subdomain"
    assert re.search(r"zendesk\.com", out.metadata["hint"])


# ---------------------------------------------------------------- auth

def test_basic_auth_header_is_email_slash_token_colon_api_token():
    tool = ZendeskTool(credential_store=_store())
    record = _store().get("zendesk")
    headers = tool._headers(record)
    auth = headers["authorization"]
    assert auth.startswith("Basic ")
    decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
    assert decoded == "alice@acme.com/token:demo123"
    assert headers["content-type"] == "application/json"


# ---------------------------------------------------------------- tickets

def test_search_tickets_happy_path():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "results": [
                {
                    "id": 1,
                    "status": "open",
                    "subject": "Login broken",
                    "url": "https://acme.zendesk.com/api/v2/tickets/1.json",
                },
                {
                    "id": 2,
                    "status": "pending",
                    "subject": "Refund",
                    "url": "https://acme.zendesk.com/api/v2/tickets/2.json",
                },
            ],
            "count": 2,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="search_tickets",
        query="type:ticket status:open priority:high",
        per_page=25,
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v2/search.json"
    assert call["query"]["query"] == "type:ticket status:open priority:high"
    assert call["query"]["per_page"] == 25
    assert "#1 [open] Login broken" in out.text
    assert out.metadata["count"] == 2
    assert out.metadata["total_count"] == 2


def test_get_ticket_rich_text():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "ticket": {
                "id": 42,
                "status": "open",
                "subject": "Hello",
                "priority": "high",
                "requester": {"name": "Bob", "email": "bob@x.com"},
                "tags": ["billing", "vip"],
                "comments": [{"body": "Please help"}],
            }
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_ticket", id=42)
    assert captured[0]["path"] == "/api/v2/tickets/42"
    assert "#42" in out.text
    assert "high" in out.text
    assert "Bob" in out.text
    assert "bob@x.com" in out.text
    assert "billing" in out.text
    assert "Please help" in out.text


def test_list_tickets_with_pagination():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "tickets": [
                {"id": 1, "status": "open", "subject": "A", "url": "u1"},
                {"id": 2, "status": "open", "subject": "B", "url": "u2"},
            ],
            "count": 50,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_tickets",
        per_page=25,
        page=3,
    )
    assert captured[0]["path"] == "/api/v2/tickets.json"
    assert captured[0]["query"] == {"per_page": 25, "page": 3}
    assert "#1" in out.text and "#2" in out.text
    assert out.metadata["total_count"] == 50


# -------------------------------------------------------------- write guards

def test_create_ticket_blocked_without_allow_writes():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture({"ticket": {"id": 1}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_ticket",
        subject="S",
        body="B",
        requester_email="x@y.com",
    )
    assert out.metadata["error"] == "writes_disabled"
    assert out.metadata["action"] == "create_ticket"
    assert captured == []


def test_update_ticket_blocked_without_allow_writes():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture({"ticket": {"id": 1}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="update_ticket",
        id=1,
        priority="high",
    )
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []


def test_close_ticket_blocked_without_allow_writes():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture({"ticket": {"id": 1, "status": "closed"}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="close_ticket", id=1)
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []


# -------------------------------------------------------------- write paths

def test_create_ticket_body_nests_under_ticket_key():
    tool = ZendeskTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"ticket": {"id": 100, "subject": "New"}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_ticket",
        subject="New",
        body="Please help",
        requester_email="bob@x.com",
        priority="urgent",
        tags=["billing", "vip"],
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v2/tickets"
    ticket_body = call["body"]["ticket"]
    assert ticket_body["subject"] == "New"
    assert ticket_body["comment"] == {"body": "Please help"}
    assert ticket_body["requester"] == {"email": "bob@x.com"}
    assert ticket_body["priority"] == "urgent"
    assert ticket_body["tags"] == ["billing", "vip"]
    assert "#100" in out.text


def test_update_ticket_sends_nested_ticket_fields():
    tool = ZendeskTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"ticket": {"id": 7}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="update_ticket",
        id=7,
        priority="low",
        tags=["escalated"],
    )
    call = captured[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/api/v2/tickets/7"
    assert call["body"] == {
        "ticket": {"priority": "low", "tags": ["escalated"]}
    }
    assert "updated" in out.text


def test_close_ticket_sends_status_closed():
    tool = ZendeskTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"ticket": {"id": 7, "status": "closed"}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="close_ticket", id=7)
    call = captured[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/api/v2/tickets/7"
    assert call["body"] == {"ticket": {"status": "closed"}}
    assert "Closed" in out.text


# ---------------------------------------------------------------- comments

def test_add_comment_works_without_allow_writes():
    tool = ZendeskTool(credential_store=_store())  # allow_writes=False
    captured, fake = _capture({"ticket": {"id": 7}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="add_comment",
        id=7,
        body="Ack, looking at it.",
    )
    call = captured[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/api/v2/tickets/7"
    assert call["body"] == {
        "ticket": {
            "comment": {"body": "Ack, looking at it.", "public": True}
        }
    }
    assert out.metadata["public"] is True
    assert "Comment added" in out.text


def test_add_comment_internal_note_pass_through():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture({"ticket": {"id": 7}})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="add_comment",
        id=7,
        body="internal only",
        public=False,
    )
    assert captured[0]["body"] == {
        "ticket": {
            "comment": {"body": "internal only", "public": False}
        }
    }
    assert out.metadata["public"] is False
    assert "internal" in out.text


# ------------------------------------------------------------------ users

def test_get_user():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "user": {
                "id": 5,
                "name": "Carol",
                "email": "carol@x.com",
                "role": "end-user",
            }
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_user", id=5)
    assert captured[0]["path"] == "/api/v2/users/5"
    assert "Carol" in out.text
    assert "carol@x.com" in out.text


def test_search_users():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "users": [
                {"id": 5, "name": "Carol", "email": "carol@x.com"},
                {"id": 6, "name": "Dan", "email": "dan@x.com"},
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="search_users",
        query="acme.com",
    )
    assert captured[0]["path"] == "/api/v2/users/search.json"
    assert captured[0]["query"] == {"query": "acme.com"}
    assert "Carol" in out.text
    assert "Dan" in out.text
    assert out.metadata["count"] == 2


# ------------------------------------------------------------------ macros

def test_list_macros_personal_access():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {
            "macros": [
                {"id": 11, "title": "Ask for logs"},
                {"id": 12, "title": "Close as spam"},
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="list_macros")
    assert captured[0]["path"] == "/api/v2/macros.json"
    assert captured[0]["query"] == {"access": "personal"}
    assert "Ask for logs" in out.text
    assert out.metadata["count"] == 2


def test_apply_macro_is_preview():
    tool = ZendeskTool(credential_store=_store())
    captured, fake = _capture(
        {"result": {"ticket": {"id": 7, "status": "pending"}}}
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="apply_macro",
        id=7,
        macro_id=11,
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v2/tickets/7/macros/11/apply"
    assert "preview" in out.text.lower()
    assert out.metadata["preview"] == {"ticket": {"id": 7, "status": "pending"}}


# ----------------------------------------------------------------- errors

def test_rate_limit_429_surfaces_retry_after_seconds():
    tool = ZendeskTool(credential_store=_store())

    def raise_429(**_kwargs):
        raise _http_error(
            429,
            body=b'{"error":"RateLimited","description":"Too many requests"}',
            headers={"Retry-After": "93"},
        )

    tool._request_json = raise_429  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="search_tickets",
        query="status:open",
    )
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after_seconds"] == 93
    assert out.metadata["status"] == 429


def test_http_error_uses_zendesk_description():
    tool = ZendeskTool(credential_store=_store())

    def raise_404(**_kwargs):
        raise _http_error(
            404,
            body=b'{"error":"RecordNotFound","description":"Ticket not found"}',
        )

    tool._request_json = raise_404  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action="get_ticket", id=999)
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 404
    assert out.metadata["message"] == "Ticket not found"
    assert "404" in out.text


# keep pytest import
assert pytest is not None
