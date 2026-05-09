from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.salesforce import SALESFORCE_PROMPT, SalesforceTool


# ---------------------------------------------------------------- helpers

def _store(
    token: str = "00D...00!sess",
    instance: str | None = "https://acme.my.salesforce.com",
):
    s = InMemoryCredentialStore()
    metadata: dict = {"auth_scheme": "Bearer"}
    if instance is not None:
        metadata["base_url"] = instance
    s.set(
        CredentialRecord(
            key="salesforce",
            provider="salesforce",
            secrets={"access_token": token},
            metadata=metadata,
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


def _http_error(
    code: int,
    body: bytes = b'[{"message":"Boom","errorCode":"BOOM"}]',
    headers: dict | None = None,
):
    return HTTPError(
        url="https://acme.my.salesforce.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata

def test_tool_name_and_description():
    tool = SalesforceTool()
    assert tool.name == "salesforce"
    assert "Salesforce" in tool.description
    assert tool.provider == "salesforce"
    assert SALESFORCE_PROMPT in tool.prompt


def test_schema_contains_full_action_enum():
    actions = (
        SalesforceTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
        "search",
        "query",
        "get_record",
        "list_accounts",
        "list_opportunities",
        "list_contacts",
        "create_record",
        "update_record",
        "log_activity",
    } == set(actions)


def test_unknown_action_returns_structured_error():
    tool = SalesforceTool(credential_store=_store())
    result = tool.run(context=_ctx(_store()), action="nope")
    assert result.metadata["error"] == "unsupported_action"
    assert "unsupported action" in result.text.lower()


def test_not_connected_when_no_credential_store():
    tool = SalesforceTool()
    result = tool.run(context=ToolContext(prompt="x"), action="query", soql="x")
    assert result.metadata["connected"] is False
    assert "not connected" in result.text.lower()


def test_missing_instance_url_reports_error():
    store = _store(instance=None)
    tool = SalesforceTool(credential_store=store)
    result = tool.run(context=_ctx(store), action="query", soql="SELECT Id FROM Account")
    assert result.metadata["error"] == "missing_instance_url"
    assert "instance URL" in result.metadata.get("hint", "")


# ---------------------------------------------------------------- write guard

def test_create_record_blocked_when_writes_disabled():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture({})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_record",
        sobject="Account",
        fields={"Name": "Acme"},
    )
    assert out.metadata["error"] == "writes_disabled"
    assert "allow_writes=True" in out.metadata["hint"]
    assert captured == []  # no network call


def test_update_record_blocked_when_writes_disabled():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture({})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="update_record",
        sobject="Account",
        record_id="001xx",
        fields={"Name": "New"},
    )
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []


def test_create_record_works_when_writes_enabled():
    tool = SalesforceTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"id": "001ABC", "success": True})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_record",
        sobject="Account",
        fields={"Name": "Acme"},
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/services/data/v60.0/sobjects/Account"
    assert call["body"] == {"Name": "Acme"}
    assert out.metadata["id"] == "001ABC"
    assert "001ABC" in out.text


def test_update_record_works_when_writes_enabled():
    tool = SalesforceTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture(None)
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="update_record",
        sobject="Account",
        record_id="001ABC",
        fields={"Industry": "Tech"},
    )
    call = captured[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/services/data/v60.0/sobjects/Account/001ABC"
    assert call["body"] == {"Industry": "Tech"}
    assert out.metadata["updated_fields"] == ["Industry"]


# ---------------------------------------------------------------- log_activity

def test_log_activity_always_works_even_when_writes_disabled():
    tool = SalesforceTool(credential_store=_store(), allow_writes=False)
    captured, fake = _capture({"id": "00TXYZ", "success": True})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="log_activity",
        subject="Called customer",
        description="Left voicemail",
        related_to_id="001ABC",
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/services/data/v60.0/sobjects/Task"
    assert call["body"]["Subject"] == "Called customer"
    assert call["body"]["Description"] == "Left voicemail"
    assert call["body"]["WhatId"] == "001ABC"
    assert out.metadata["id"] == "00TXYZ"
    assert "Called customer" in out.text


def test_log_activity_works_when_writes_enabled_too():
    tool = SalesforceTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"id": "00TABC"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="log_activity",
        subject="Follow up",
    )
    assert captured[0]["path"] == "/services/data/v60.0/sobjects/Task"
    assert captured[0]["body"] == {"Subject": "Follow up"}
    assert out.metadata["id"] == "00TABC"


# ---------------------------------------------------------------- query / search

def test_query_happy_path_returns_total_size_and_path():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture(
        {
            "totalSize": 2,
            "done": True,
            "records": [
                {"attributes": {"type": "Account"}, "Id": "001A", "Name": "Acme"},
                {"attributes": {"type": "Account"}, "Id": "001B", "Name": "Globex"},
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    soql = "SELECT Id, Name FROM Account LIMIT 10"
    out = tool.run(context=_ctx(_store()), action="query", soql=soql)
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/services/data/v60.0/query"
    assert call["query"] == {"q": soql}
    assert "totalSize: 2" in out.text
    assert "Acme" in out.text
    assert out.metadata["totalSize"] == 2
    assert out.metadata["soql"] == soql


def test_search_happy_path():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture(
        {
            "searchRecords": [
                {"attributes": {"type": "Account"}, "Id": "001A", "Name": "Acme"},
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    sosl = "FIND {acme} IN ALL FIELDS RETURNING Account(Id, Name)"
    out = tool.run(context=_ctx(_store()), action="search", query=sosl)
    call = captured[0]
    assert call["path"] == "/services/data/v60.0/search"
    assert call["query"] == {"q": sosl}
    assert "totalSize: 1" in out.text
    assert out.metadata["totalSize"] == 1


# ---------------------------------------------------------------- list_* wrappers

def test_list_accounts_generates_expected_soql():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture({"totalSize": 0, "done": True, "records": []})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="list_accounts", limit=25)
    call = captured[0]
    assert call["path"] == "/services/data/v60.0/query"
    assert call["query"]["q"] == (
        "SELECT Id, Name, Industry, Website, AnnualRevenue FROM Account LIMIT 25"
    )


def test_list_opportunities_generates_expected_soql():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture({"totalSize": 0, "done": True, "records": []})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="list_opportunities", limit=5)
    assert captured[0]["query"]["q"] == (
        "SELECT Id, Name, StageName, Amount, CloseDate, AccountId FROM "
        "Opportunity WHERE IsClosed = false LIMIT 5"
    )


def test_list_contacts_generates_expected_soql():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture({"totalSize": 0, "done": True, "records": []})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="list_contacts", limit=50)
    assert captured[0]["query"]["q"] == (
        "SELECT Id, FirstName, LastName, Email, Title, AccountId FROM "
        "Contact LIMIT 50"
    )


# ---------------------------------------------------------------- get_record

def test_get_record_happy_path():
    tool = SalesforceTool(credential_store=_store())
    captured, fake = _capture(
        {
            "attributes": {"type": "Account"},
            "Id": "001ABC",
            "Name": "Acme",
            "Industry": "Tech",
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_record",
        sobject="Account",
        record_id="001ABC",
    )
    assert captured[0]["method"] == "GET"
    assert captured[0]["path"] == "/services/data/v60.0/sobjects/Account/001ABC"
    assert out.metadata["sobject"] == "Account"
    assert out.metadata["record_id"] == "001ABC"
    assert "Acme" in out.text


# ---------------------------------------------------------------- error paths

def test_401_returns_auth_expired():
    tool = SalesforceTool(credential_store=_store())

    def raise_401(**_kwargs):
        raise _http_error(
            401, body=b'[{"message":"Session expired","errorCode":"INVALID_SESSION_ID"}]'
        )

    tool._request_json = raise_401  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="query",
        soql="SELECT Id FROM Account",
    )
    assert out.metadata["error"] == "auth_expired"
    assert out.metadata["status"] == 401
    assert "refresh" in out.text.lower()


def test_429_returns_rate_limited_with_retry_after_seconds():
    tool = SalesforceTool(credential_store=_store())

    def raise_429(**_kwargs):
        raise _http_error(
            429,
            body=b'[{"message":"Too Many Requests","errorCode":"REQUEST_LIMIT_EXCEEDED"}]',
            headers={"Retry-After": "42"},
        )

    tool._request_json = raise_429  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="query",
        soql="SELECT Id FROM Account",
    )
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after_seconds"] == 42
    assert out.metadata["status"] == 429


def test_other_http_error_surfaces_status_and_message():
    tool = SalesforceTool(credential_store=_store())

    def raise_404(**_kwargs):
        raise _http_error(
            404, body=b'[{"message":"Not Found","errorCode":"NOT_FOUND"}]'
        )

    tool._request_json = raise_404  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_record",
        sobject="Account",
        record_id="001missing",
    )
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 404
    assert out.metadata["message"] == "Not Found"
    assert "404" in out.text


# ---------------------------------------------------------------- extras

def test_api_version_is_used_in_paths():
    tool = SalesforceTool(credential_store=_store(), api_version="v59.0")
    captured, fake = _capture({"totalSize": 0, "done": True, "records": []})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(_store()), action="query", soql="SELECT Id FROM Account")
    assert captured[0]["path"] == "/services/data/v59.0/query"


def test_create_record_missing_fields_returns_missing_parameter():
    tool = SalesforceTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"id": "001"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_record",
        sobject="Account",
    )
    assert out.metadata["error"] == "missing_parameter"
    assert captured == []


# keep pytest import used
assert pytest is not None
