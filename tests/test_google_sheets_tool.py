from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.google_sheets import GOOGLE_SHEETS_PROMPT, GoogleSheetsTool


# ---------------------------------------------------------------- helpers


def _store(token="ya29.demo", *, include_base_url=True, include_scheme=True):
    s = InMemoryCredentialStore()
    metadata: dict = {}
    if include_base_url:
        metadata["base_url"] = "https://sheets.googleapis.com"
    if include_scheme:
        metadata["auth_scheme"] = "Bearer"
    s.set(
        CredentialRecord(
            key="google_sheets",
            provider="google_sheets",
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


def _http_error(code: int, body: bytes = b"{}", headers: dict | None = None):
    return HTTPError(
        url="https://sheets.googleapis.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata


def test_tool_name_description_and_provider():
    tool = GoogleSheetsTool()
    assert tool.name == "google_sheets"
    assert tool.provider == "google_sheets"
    assert "Google Sheets" in tool.description
    assert GOOGLE_SHEETS_PROMPT in tool.prompt
    assert tool.allow_writes is False


def test_schema_contains_full_action_enum():
    actions = (
        GoogleSheetsTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
        "get_values",
        "update_values",
        "append_values",
        "clear_values",
        "batch_get",
        "get_metadata",
        "create_spreadsheet",
        "add_sheet",
    } == set(actions)


def test_unknown_action_returns_structured_error():
    tool = GoogleSheetsTool(credential_store=_store())
    result = tool.run(context=_ctx(_store()), action="nope")
    assert result.metadata["error"] == "unsupported_action"
    assert "unsupported action" in result.text.lower()


def test_not_connected_when_no_credential_store():
    tool = GoogleSheetsTool()
    result = tool.run(context=ToolContext(prompt="x"), action="get_values")
    assert result.metadata["connected"] is False
    assert "not connected" in result.text.lower()


def test_default_base_url_and_auth_scheme_fallback():
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="google_sheets",
            provider="google_sheets",
            secrets={"access_token": "ya29.demo"},
            metadata={},
        )
    )
    tool = GoogleSheetsTool(credential_store=store)
    _captured, fake = _capture({"values": []})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(store),
        action="get_values",
        spreadsheet_id="abc",
        range="Sheet1!A1:B2",
    )
    record = store.get("google_sheets")
    assert record.metadata["base_url"] == "https://sheets.googleapis.com"
    assert record.metadata["auth_scheme"] == "Bearer"


# ---------------------------------------------------------------- get_values


def test_get_values_encodes_range_and_passes_render_option():
    tool = GoogleSheetsTool(credential_store=_store())
    captured, fake = _capture(
        {
            "range": "Sheet1!A1:C2",
            "values": [["a", "b", "c"], ["1", "2", "3"]],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_values",
        spreadsheet_id="SHEET_123",
        range="Sheet 1!A1:C2",
        value_render_option="UNFORMATTED_VALUE",
    )
    call = captured[0]
    assert call["method"] == "GET"
    # Spaces and ! must be percent-encoded.
    assert call["path"] == (
        "/v4/spreadsheets/SHEET_123/values/Sheet%201%21A1%3AC2"
    )
    assert call["query"] == {"valueRenderOption": "UNFORMATTED_VALUE"}
    assert out.metadata["row_count"] == 2
    assert out.metadata["value_render_option"] == "UNFORMATTED_VALUE"
    # Markdown table with header + divider + 1 data row
    assert "| a | b | c |" in out.text
    assert "| --- | --- | --- |" in out.text


def test_get_values_default_render_option_is_formatted_value():
    tool = GoogleSheetsTool(credential_store=_store())
    captured, fake = _capture({"values": [["x"]]})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(_store()),
        action="get_values",
        spreadsheet_id="abc",
        range="A1",
    )
    assert captured[0]["query"] == {"valueRenderOption": "FORMATTED_VALUE"}


# ---------------------------------------------------------------- writes gate


@pytest.mark.parametrize(
    "action,extra",
    [
        ("update_values", {"spreadsheet_id": "a", "range": "A1", "values": [["x"]]}),
        ("append_values", {"spreadsheet_id": "a", "range": "A1", "values": [["x"]]}),
        ("clear_values", {"spreadsheet_id": "a", "range": "A1"}),
        ("create_spreadsheet", {"title": "New"}),
        ("add_sheet", {"spreadsheet_id": "a", "title": "Tab2"}),
    ],
)
def test_writes_disabled_by_default(action, extra):
    tool = GoogleSheetsTool(credential_store=_store())
    captured, fake = _capture({})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(_store()), action=action, **extra)
    assert out.metadata["error"] == "writes_disabled"
    assert captured == []  # never hit the network


# ---------------------------------------------------------------- update_values


def test_update_values_body_shape_and_path():
    tool = GoogleSheetsTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture(
        {
            "updatedRange": "Sheet1!A1:B2",
            "updatedCells": 4,
            "updatedRows": 2,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    values = [["h1", "h2"], ["v1", "v2"]]
    out = tool.run(
        context=_ctx(_store()),
        action="update_values",
        spreadsheet_id="SID",
        range="Sheet1!A1:B2",
        values=values,
    )
    call = captured[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/v4/spreadsheets/SID/values/Sheet1%21A1%3AB2"
    assert call["query"] == {"valueInputOption": "USER_ENTERED"}
    assert call["body"] == {"values": values}
    # Body is a nested 2D list, not flat.
    assert isinstance(call["body"]["values"], list)
    assert isinstance(call["body"]["values"][0], list)
    assert out.metadata["updated_cells"] == 4


# ---------------------------------------------------------------- append_values


def test_append_values_url_has_append_suffix():
    tool = GoogleSheetsTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture(
        {
            "tableRange": "Sheet1!A1:B2",
            "updates": {"updatedCells": 2, "updatedRows": 1},
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="append_values",
        spreadsheet_id="SID",
        range="Sheet1!A:B",
        values=[["v1", "v2"]],
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"].endswith(":append")
    assert call["path"] == "/v4/spreadsheets/SID/values/Sheet1%21A%3AB:append"
    assert call["query"] == {"valueInputOption": "USER_ENTERED"}
    assert call["body"] == {"values": [["v1", "v2"]]}
    assert out.metadata["updated_rows"] == 1


# ---------------------------------------------------------------- clear_values


def test_clear_values_url_has_clear_suffix_and_empty_body():
    tool = GoogleSheetsTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture({"clearedRange": "Sheet1!A1:Z1000"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="clear_values",
        spreadsheet_id="SID",
        range="Sheet1!A1:Z1000",
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"].endswith(":clear")
    assert call["body"] == {}
    assert "Sheet1!A1:Z1000" in out.text


# ---------------------------------------------------------------- batch_get


def test_batch_get_with_multiple_ranges():
    tool = GoogleSheetsTool(credential_store=_store())
    captured, fake = _capture(
        {
            "valueRanges": [
                {"range": "Sheet1!A1:A3", "values": [["a"], ["b"], ["c"]]},
                {"range": "Sheet2!B1:B2", "values": [["x"], ["y"]]},
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="batch_get",
        spreadsheet_id="SID",
        ranges=["Sheet1!A1:A3", "Sheet2!B1:B2"],
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/v4/spreadsheets/SID/values:batchGet"
    # `ranges` should be repeated in the querystring — urlencode does this
    # via `doseq=True`, so we keep it as a list here.
    assert call["query"] == {"ranges": ["Sheet1!A1:A3", "Sheet2!B1:B2"]}
    assert out.metadata["count"] == 2
    assert "Sheet1!A1:A3" in out.text
    assert "Sheet2!B1:B2" in out.text


# ---------------------------------------------------------------- get_metadata


def test_get_metadata_returns_titles_and_dimensions():
    tool = GoogleSheetsTool(credential_store=_store())
    captured, fake = _capture(
        {
            "spreadsheetId": "SID",
            "properties": {"title": "Q4 Plan"},
            "sheets": [
                {
                    "properties": {
                        "sheetId": 0,
                        "title": "Forecast",
                        "gridProperties": {"rowCount": 100, "columnCount": 26},
                    },
                },
                {
                    "properties": {
                        "sheetId": 1,
                        "title": "Actuals",
                        "gridProperties": {"rowCount": 200, "columnCount": 12},
                    },
                },
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_metadata",
        spreadsheet_id="SID",
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/v4/spreadsheets/SID"
    assert call["query"] == {"includeGridData": "false"}
    assert out.metadata["count"] == 2
    assert {s["title"] for s in out.metadata["sheets"]} == {"Forecast", "Actuals"}
    assert "Forecast (id=0): 100 rows x 26 cols" in out.text
    assert "Q4 Plan" in out.text


# ---------------------------------------------------------------- create_spreadsheet


def test_create_spreadsheet_body_shape_when_writes_enabled():
    tool = GoogleSheetsTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture(
        {
            "spreadsheetId": "NEW_ID",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/NEW_ID",
            "properties": {"title": "My Report"},
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_spreadsheet",
        title="My Report",
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v4/spreadsheets"
    assert call["body"] == {"properties": {"title": "My Report"}}
    assert out.metadata["spreadsheet_id"] == "NEW_ID"


# ---------------------------------------------------------------- add_sheet


def test_add_sheet_batch_update_shape_when_writes_enabled():
    tool = GoogleSheetsTool(credential_store=_store(), allow_writes=True)
    captured, fake = _capture(
        {
            "spreadsheetId": "SID",
            "replies": [
                {
                    "addSheet": {
                        "properties": {"sheetId": 123, "title": "Logs"},
                    },
                },
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="add_sheet",
        spreadsheet_id="SID",
        title="Logs",
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v4/spreadsheets/SID:batchUpdate"
    assert call["body"] == {
        "requests": [{"addSheet": {"properties": {"title": "Logs"}}}],
    }
    assert out.metadata["sheet_id"] == 123


# ---------------------------------------------------------------- errors


def test_429_returns_rate_limited_with_retry_after():
    tool = GoogleSheetsTool(credential_store=_store())

    def raise_rate_limit(**_kwargs):
        raise _http_error(
            429,
            body=b'{"error":{"message":"Quota exceeded"}}',
            headers={"Retry-After": "42"},
        )

    tool._request_json = raise_rate_limit  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_values",
        spreadsheet_id="a",
        range="A1",
    )
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after_seconds"] == 42
    assert out.metadata["status"] == 429


def test_403_quota_returns_quota_exceeded_with_metric():
    tool = GoogleSheetsTool(credential_store=_store())

    body = (
        b'{"error":{"code":403,"message":"Quota exceeded",'
        b'"errors":[{"reason":"rateLimitExceeded","message":"Quota"}],'
        b'"details":[{"@type":"type.googleapis.com/google.rpc.QuotaFailure",'
        b'"violations":[{"quotaMetric":"sheets.googleapis.com/read_requests",'
        b'"quotaId":"ReadRequestsPerMinutePerUser"}]}]}}'
    )

    def raise_quota(**_kwargs):
        raise _http_error(403, body=body, headers={})

    tool._request_json = raise_quota  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_values",
        spreadsheet_id="a",
        range="A1",
    )
    assert out.metadata["error"] == "quota_exceeded"
    assert out.metadata["status"] == 403
    assert out.metadata["quota_reason"] == "rateLimitExceeded"
    assert out.metadata["quota_metric"] == "sheets.googleapis.com/read_requests"
    assert "sheets.googleapis.com/read_requests" in out.text


# reference import so lints don't complain
assert pytest is not None
