from __future__ import annotations

import base64
import io
import urllib.error
from types import SimpleNamespace
from typing import Any

from shipit_agent import CredentialRecord
from shipit_agent.integrations import InMemoryCredentialStore
from shipit_agent.tools.gitlab import GitLabTool


def _store(token: str = "glpat-test", base_url: str = "https://gitlab.com"):
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="gitlab",
            provider="gitlab",
            secrets={"token": token},
            metadata={"base_url": base_url},
        )
    )
    return store


def _context(store):
    return SimpleNamespace(state={"credential_store": store})


def _patch(tool: GitLabTool, handler):
    calls: list[dict[str, Any]] = []

    def fake_request_json(*, record, method, path, query=None, body=None):
        calls.append(
            {
                "record": record,
                "method": method,
                "path": path,
                "query": query,
                "body": body,
            }
        )
        return handler(method=method, path=path, query=query, body=body)

    tool._request_json = fake_request_json  # type: ignore[method-assign]
    return calls


def _http_error(
    status: int, headers: dict[str, str] | None = None, body: bytes = b"{}"
) -> urllib.error.HTTPError:
    hdrs = headers or {}
    return urllib.error.HTTPError(
        "https://gitlab.com/api/v4/issues",
        status,
        "err",
        hdrs,  # type: ignore[arg-type]
        io.BytesIO(body),
    )


# ── schema / metadata ─────────────────────────────────────────────


def test_tool_name_and_description() -> None:
    tool = GitLabTool()
    assert tool.name == "gitlab"
    assert "gitlab" in tool.description.lower()
    assert tool.provider == "gitlab"


def test_schema_enum_contains_all_actions() -> None:
    actions = GitLabTool().schema()["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
    expected = {
        "search_issues",
        "get_issue",
        "create_issue",
        "close_issue",
        "comment_issue",
        "list_merge_requests",
        "get_merge_request",
        "create_merge_request",
        "merge_merge_request",
        "approve_merge_request",
        "comment_merge_request",
        "get_file",
        "list_pipelines",
        "get_pipeline",
        "retry_pipeline",
        "cancel_pipeline",
    }
    assert set(actions) == expected


def test_unknown_action_returns_structured_error() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    result = tool.run(context=ctx, action="not_a_real_action")
    assert result.metadata["error"] == "unsupported_action"
    assert "not_a_real_action" in result.text.lower()


def test_not_connected_output_without_credentials() -> None:
    tool = GitLabTool()
    ctx = SimpleNamespace(state={})
    result = tool.run(context=ctx, action="search_issues")
    assert result.metadata["connected"] is False
    assert result.metadata["provider"] == "gitlab"
    assert "not connected" in result.text.lower()


# ── project id encoding & base url ────────────────────────────────


def test_project_id_path_is_url_encoded() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(
        tool,
        lambda **_: {"iid": 5, "title": "hi", "state": "opened", "web_url": "u"},
    )
    tool.run(context=ctx, action="get_issue", project_id="myorg/myrepo", iid=5)
    assert calls, "expected a request to be made"
    assert "myorg%2Fmyrepo" in calls[0]["path"]
    assert "myorg/myrepo" not in calls[0]["path"]


def test_project_id_numeric_is_passed_through() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(
        tool,
        lambda **_: {"iid": 5, "title": "hi", "state": "opened", "web_url": "u"},
    )
    tool.run(context=ctx, action="get_issue", project_id="278964", iid=5)
    assert "/projects/278964/" in calls[0]["path"]


def test_default_base_url_when_missing() -> None:
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="gitlab",
            provider="gitlab",
            secrets={"token": "glpat"},
            metadata={},
        )
    )
    tool = GitLabTool(credential_store=store)
    record = store.get("gitlab")
    assert tool._base_url(record) == "https://gitlab.com"


def test_custom_base_url_from_metadata() -> None:
    store = _store(base_url="https://gitlab.example.com/")
    tool = GitLabTool(credential_store=store)
    record = store.get("gitlab")
    # trailing slash stripped
    assert tool._base_url(record) == "https://gitlab.example.com"


# ── issue actions ─────────────────────────────────────────────────


def test_search_issues_happy_path() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    items = [
        {
            "iid": 1,
            "title": "Bug in login",
            "state": "opened",
            "web_url": "https://gitlab.com/x/1",
        },
        {
            "iid": 2,
            "title": "Docs typo",
            "state": "closed",
            "web_url": "https://gitlab.com/x/2",
        },
    ]
    calls = _patch(tool, lambda **_: items)
    result = tool.run(context=ctx, action="search_issues", query="login")
    assert calls[0]["path"] == "/api/v4/issues"
    assert calls[0]["query"]["scope"] == "all"
    assert calls[0]["query"]["search"] == "login"
    assert "!1" in result.text and "Bug in login" in result.text
    assert result.metadata["count"] == 2
    assert result.metadata["items"] == items


def test_get_issue_returns_rich_summary() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    _patch(
        tool,
        lambda **_: {
            "iid": 42,
            "title": "Fix flaky test",
            "state": "opened",
            "description": "Flake on CI",
            "author": {"username": "alice"},
            "web_url": "https://gitlab.com/x/42",
        },
    )
    result = tool.run(
        context=ctx, action="get_issue", project_id="myorg/myrepo", iid=42
    )
    assert "!42" in result.text
    assert "Fix flaky test" in result.text
    assert "alice" in result.text
    assert result.metadata["issue"]["iid"] == 42


def test_create_issue_with_labels_and_assignees() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(
        tool,
        lambda **_: {
            "iid": 10,
            "title": "New bug",
            "web_url": "https://gitlab.com/x/10",
        },
    )
    result = tool.run(
        context=ctx,
        action="create_issue",
        project_id="myorg/myrepo",
        title="New bug",
        description_text="Reproduction steps",
        labels="bug,backend",
        assignee_ids=[7, 8],
    )
    body = calls[0]["body"]
    assert body["title"] == "New bug"
    assert body["description"] == "Reproduction steps"
    assert body["labels"] == "bug,backend"
    assert body["assignee_ids"] == [7, 8]
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/issues")
    assert "!10" in result.text


def test_close_issue_sends_state_event() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"iid": 5, "state": "closed"})
    result = tool.run(
        context=ctx, action="close_issue", project_id="myorg/myrepo", iid=5
    )
    assert calls[0]["method"] == "PUT"
    assert calls[0]["body"] == {"state_event": "close"}
    assert "closed" in result.text.lower()


def test_comment_issue_posts_note() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"id": 99, "body": "looks good"})
    result = tool.run(
        context=ctx,
        action="comment_issue",
        project_id="myorg/myrepo",
        iid=5,
        body="looks good",
    )
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/issues/5/notes")
    assert calls[0]["body"] == {"body": "looks good"}
    assert "Comment added" in result.text


# ── merge request actions ─────────────────────────────────────────


def test_list_merge_requests_with_state() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    mrs = [
        {
            "iid": 3,
            "title": "Refactor",
            "state": "opened",
            "web_url": "https://gitlab.com/x/!3",
        }
    ]
    calls = _patch(tool, lambda **_: mrs)
    result = tool.run(
        context=ctx,
        action="list_merge_requests",
        project_id="myorg/myrepo",
        state="opened",
    )
    assert calls[0]["query"]["state"] == "opened"
    assert calls[0]["path"].endswith("/merge_requests")
    assert "!3" in result.text
    assert result.metadata["count"] == 1


def test_get_merge_request_returns_branches() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    _patch(
        tool,
        lambda **_: {
            "iid": 7,
            "title": "Feature",
            "state": "opened",
            "source_branch": "feat/x",
            "target_branch": "main",
            "author": {"username": "bob"},
            "web_url": "https://gitlab.com/x/!7",
        },
    )
    result = tool.run(
        context=ctx,
        action="get_merge_request",
        project_id="myorg/myrepo",
        mr_iid=7,
    )
    assert "feat/x" in result.text
    assert "main" in result.text
    assert "bob" in result.text


def test_create_merge_request_posts_branches() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(
        tool,
        lambda **_: {
            "iid": 11,
            "title": "New MR",
            "web_url": "https://gitlab.com/x/!11",
        },
    )
    result = tool.run(
        context=ctx,
        action="create_merge_request",
        project_id="myorg/myrepo",
        source_branch="feat/new",
        target_branch="main",
        title="New MR",
        description_text="body",
    )
    body = calls[0]["body"]
    assert body["source_branch"] == "feat/new"
    assert body["target_branch"] == "main"
    assert body["title"] == "New MR"
    assert calls[0]["method"] == "POST"
    assert "!11" in result.text


def test_merge_merge_request_puts_to_merge_endpoint() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"iid": 7, "state": "merged"})
    result = tool.run(
        context=ctx,
        action="merge_merge_request",
        project_id="myorg/myrepo",
        mr_iid=7,
    )
    assert calls[0]["method"] == "PUT"
    assert calls[0]["path"].endswith("/merge_requests/7/merge")
    assert "merged" in result.text.lower()


def test_approve_merge_request_posts_approve() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"approved": True})
    result = tool.run(
        context=ctx,
        action="approve_merge_request",
        project_id="myorg/myrepo",
        mr_iid=7,
    )
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/merge_requests/7/approve")
    assert "approved" in result.text.lower()


def test_comment_merge_request_posts_note() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"id": 1, "body": "LGTM"})
    result = tool.run(
        context=ctx,
        action="comment_merge_request",
        project_id="myorg/myrepo",
        mr_iid=7,
        body="LGTM",
    )
    assert calls[0]["path"].endswith("/merge_requests/7/notes")
    assert calls[0]["body"] == {"body": "LGTM"}
    assert "Comment added" in result.text


# ── file & pipelines ──────────────────────────────────────────────


def test_get_file_decodes_base64() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    original = "print('hello gitlab')\n"
    encoded = base64.b64encode(original.encode("utf-8")).decode("utf-8")
    calls = _patch(
        tool,
        lambda **_: {
            "file_name": "main.py",
            "file_path": "src/main.py",
            "encoding": "base64",
            "content": encoded,
        },
    )
    result = tool.run(
        context=ctx,
        action="get_file",
        project_id="myorg/myrepo",
        path="src/main.py",
        ref="main",
    )
    assert result.text == original
    assert "src%2Fmain.py" in calls[0]["path"]
    assert calls[0]["query"]["ref"] == "main"
    assert result.metadata["file"]["content"] == original


def test_list_pipelines_renders_lines() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    items = [
        {
            "id": 100,
            "status": "success",
            "ref": "main",
            "sha": "abcdef1234567890",
            "web_url": "https://gitlab.com/x/-/pipelines/100",
        }
    ]
    calls = _patch(tool, lambda **_: items)
    result = tool.run(
        context=ctx, action="list_pipelines", project_id="myorg/myrepo"
    )
    assert calls[0]["path"].endswith("/pipelines")
    assert "#100" in result.text
    assert "success" in result.text
    assert result.metadata["count"] == 1


def test_get_pipeline_returns_details() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    _patch(
        tool,
        lambda **_: {
            "id": 100,
            "status": "failed",
            "ref": "main",
            "sha": "deadbeef",
            "web_url": "https://gitlab.com/x/-/pipelines/100",
        },
    )
    result = tool.run(
        context=ctx,
        action="get_pipeline",
        project_id="myorg/myrepo",
        pipeline_id=100,
    )
    assert "failed" in result.text
    assert "deadbeef" in result.text


def test_retry_pipeline_posts_retry() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"id": 100, "status": "pending"})
    result = tool.run(
        context=ctx,
        action="retry_pipeline",
        project_id="myorg/myrepo",
        pipeline_id=100,
    )
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/pipelines/100/retry")
    assert "retried" in result.text.lower()


def test_cancel_pipeline_posts_cancel() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)
    calls = _patch(tool, lambda **_: {"id": 100, "status": "canceled"})
    result = tool.run(
        context=ctx,
        action="cancel_pipeline",
        project_id="myorg/myrepo",
        pipeline_id=100,
    )
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/pipelines/100/cancel")
    assert "cancelled" in result.text.lower()


# ── error handling ────────────────────────────────────────────────


def test_rate_limit_response_includes_retry_after() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)

    def raise_429(**_):
        raise _http_error(429, headers={"Retry-After": "42"})

    _patch(tool, raise_429)
    result = tool.run(context=ctx, action="search_issues", query="x")
    assert result.metadata["error"] == "rate_limited"
    assert result.metadata["retry_after_seconds"] == 42
    assert result.metadata["status"] == 429


def test_http_error_surfaces_status_and_message() -> None:
    tool = GitLabTool(credential_store=_store())
    ctx = _context(tool.credential_store)

    def raise_404(**_):
        raise _http_error(404, body=b'{"message":"404 Project Not Found"}')

    _patch(tool, raise_404)
    result = tool.run(
        context=ctx, action="get_issue", project_id="bad/path", iid=1
    )
    assert result.metadata["error"] == "http_error"
    assert result.metadata["status"] == 404
    assert "404 Project Not Found" in result.metadata["message"]
