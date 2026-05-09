from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.figma import FIGMA_PROMPT, FigmaTool


# ---------------------------------------------------------------- helpers

def _store(token="figd_test", *, include_base_url=True):
    s = InMemoryCredentialStore()
    metadata: dict = {}
    if include_base_url:
        metadata["base_url"] = "https://api.figma.com"
    s.set(
        CredentialRecord(
            key="figma",
            provider="figma",
            secrets={"token": token},
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
    """Return (captured_list, fake_request_json) — install fake onto the tool."""
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
    body: bytes = b'{"err":"Boom"}',
    headers: dict | None = None,
):
    return HTTPError(
        url="https://api.figma.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata

def test_tool_name_and_description():
    tool = FigmaTool()
    assert tool.name == "figma"
    assert "Figma" in tool.description
    assert tool.provider == "figma"
    assert FIGMA_PROMPT in tool.prompt


def test_schema_contains_full_action_enum():
    actions = (
        FigmaTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
        "get_file",
        "get_file_nodes",
        "get_image",
        "get_comments",
        "post_comment",
        "resolve_comment",
        "get_team_projects",
        "get_project_files",
        "get_team_components",
    } == set(actions)


def test_unknown_action_returns_structured_error():
    tool = FigmaTool(credential_store=_store())
    result = tool.run(context=_ctx(_store()), action="nope")
    assert result.metadata["error"] == "unsupported_action"
    assert "unsupported action" in result.text.lower()


def test_not_connected_when_no_credential_store():
    tool = FigmaTool()
    result = tool.run(context=ToolContext(prompt="x"), action="get_file")
    assert result.metadata["connected"] is False
    assert "not connected" in result.text.lower()


def test_figma_token_header_applied_and_no_authorization():
    store = _store("figd_secret")
    tool = FigmaTool(credential_store=store)
    record = store.get("figma")
    record = tool._ensure_base_url(record)
    headers = tool._headers(record)
    assert headers.get("x-figma-token") == "figd_secret"
    assert "authorization" not in headers
    # Content-type baseline from base class preserved
    assert headers.get("content-type") == "application/json"


def test_default_base_url_fallback():
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="figma",
            provider="figma",
            secrets={"token": "figd_test"},
            metadata={},
        )
    )
    tool = FigmaTool(credential_store=store)
    captured, fake = _capture({"name": "Doc", "lastModified": "2026-01-01", "document": {"children": []}})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(store), action="get_file", file_key="ABC")
    record = store.get("figma")
    assert record.metadata["base_url"] == "https://api.figma.com"


# ---------------------------------------------------------------- files

def test_get_file_happy_path():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {
            "name": "Design System",
            "lastModified": "2026-03-01T10:00:00Z",
            "document": {
                "id": "0:0",
                "children": [
                    {"id": "1:1", "name": "Page 1"},
                    {"id": "2:2", "name": "Page 2"},
                ],
            },
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file",
        file_key="ABC123",
    )
    assert captured[0]["method"] == "GET"
    assert captured[0]["path"] == "/v1/files/ABC123"
    assert "Design System" in out.text
    assert "pages: 2" in out.text
    assert "2026-03-01T10:00:00Z" in out.text
    # Heavy document tree goes in metadata, not in text.
    assert "children" not in out.text
    assert out.metadata["file"]["name"] == "Design System"


def test_get_file_nodes_encodes_ids_query():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {"nodes": {"1:2": {"document": {"id": "1:2"}}, "3:4": {"document": {"id": "3:4"}}}}
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file_nodes",
        file_key="ABC123",
        ids=["1:2", "3:4"],
    )
    assert captured[0]["method"] == "GET"
    assert captured[0]["path"] == "/v1/files/ABC123/nodes"
    assert captured[0]["query"] == {"ids": "1:2,3:4"}
    assert out.metadata["count"] == 2
    assert "1:2" in out.text


def test_get_image_post_body_with_format_scale_and_ids():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {"images": {"1:2": "https://example.com/img.png"}}
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_image",
        file_key="ABC",
        ids=["1:2"],
        format="png",
        scale=2,
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/images/ABC"
    assert call["body"]["ids"] == "1:2"
    assert call["body"]["format"] == "png"
    assert call["body"]["scale"] == 2.0
    assert "https://example.com/img.png" in out.text
    assert out.metadata["images"]["1:2"] == "https://example.com/img.png"


# ---------------------------------------------------------------- comments

def test_get_comments_happy_path():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {
            "comments": [
                {
                    "id": "c1",
                    "message": "Tighten spacing",
                    "user": {"handle": "alice"},
                },
                {
                    "id": "c2",
                    "message": "LGTM",
                    "user": {"handle": "bob"},
                },
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_comments",
        file_key="ABC",
    )
    assert captured[0]["method"] == "GET"
    assert captured[0]["path"] == "/v1/files/ABC/comments"
    assert "Tighten spacing" in out.text
    assert out.metadata["count"] == 2


def test_post_comment_with_client_meta():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture({"id": "c99", "message": "Please fix"})
    tool._request_json = fake  # type: ignore[assignment]
    client_meta = {"node_id": "1:2", "node_offset": {"x": 10, "y": 20}}
    out = tool.run(
        context=_ctx(_store()),
        action="post_comment",
        file_key="ABC",
        message="Please fix",
        client_meta=client_meta,
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/files/ABC/comments"
    assert call["body"]["message"] == "Please fix"
    assert call["body"]["client_meta"] == client_meta
    assert "c99" in out.text


def test_resolve_comment_uses_delete():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture({})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="resolve_comment",
        file_key="ABC",
        comment_id="c1",
    )
    call = captured[0]
    assert call["method"] == "DELETE"
    assert call["path"] == "/v1/files/ABC/comments/c1"
    assert "Resolved" in out.text


# ---------------------------------------------------------------- workspace

def test_get_team_projects():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {
            "name": "Acme",
            "projects": [
                {"id": "p1", "name": "Mobile"},
                {"id": "p2", "name": "Web"},
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_team_projects",
        team_id="t-1",
    )
    assert captured[0]["path"] == "/v1/teams/t-1/projects"
    assert "Mobile" in out.text
    assert out.metadata["count"] == 2


def test_get_project_files():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {
            "files": [
                {
                    "key": "file1",
                    "name": "Homepage",
                    "last_modified": "2026-03-01",
                },
                {
                    "key": "file2",
                    "name": "Settings",
                    "last_modified": "2026-02-01",
                },
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_project_files",
        project_id="p1",
    )
    assert captured[0]["path"] == "/v1/projects/p1/files"
    assert "Homepage" in out.text
    assert "file2" in out.text
    assert out.metadata["count"] == 2


def test_get_team_components():
    tool = FigmaTool(credential_store=_store())
    captured, fake = _capture(
        {
            "meta": {
                "components": [
                    {"key": "k1", "name": "Button", "node_id": "1:1"},
                    {"key": "k2", "name": "Icon", "node_id": "2:2"},
                ]
            }
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_team_components",
        team_id="t-1",
    )
    assert captured[0]["path"] == "/v1/teams/t-1/components"
    assert "Button" in out.text
    assert out.metadata["count"] == 2


# ---------------------------------------------------------------- errors

def test_rate_limit_429_returns_retry_after_seconds():
    tool = FigmaTool(credential_store=_store())

    def raise_rate_limit(**_kwargs):
        raise _http_error(
            429,
            body=b'{"err":"rate limit"}',
            headers={"Retry-After": "42"},
        )

    tool._request_json = raise_rate_limit  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file",
        file_key="ABC",
    )
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after_seconds"] == 42
    assert out.metadata["status"] == 429


def test_other_http_error_surfaces_status_and_message():
    tool = FigmaTool(credential_store=_store())

    def raise_404(**_kwargs):
        raise _http_error(
            404,
            body=b'{"err":"Not found"}',
            headers={},
        )

    tool._request_json = raise_404  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file",
        file_key="ABC",
    )
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 404
    assert out.metadata["message"] == "Not found"
    assert "404" in out.text


# reference imports so pytest keeps them if linter wants them
assert pytest is not None
