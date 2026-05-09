from __future__ import annotations

import base64
import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.github import GITHUB_PROMPT, GitHubTool, parse_next_url


# ---------------------------------------------------------------- helpers

def _store(token="ghp_test", *, include_base_url=True, include_scheme=True):
    s = InMemoryCredentialStore()
    metadata: dict = {}
    if include_base_url:
        metadata["base_url"] = "https://api.github.com"
    if include_scheme:
        metadata["auth_scheme"] = "Bearer"
    s.set(
        CredentialRecord(
            key="github",
            provider="github",
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
    body: bytes = b'{"message":"Boom"}',
    headers: dict | None = None,
):
    return HTTPError(
        url="https://api.github.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata

def test_tool_name_and_description():
    tool = GitHubTool()
    assert tool.name == "github"
    assert "GitHub" in tool.description
    assert tool.provider == "github"
    assert GITHUB_PROMPT in tool.prompt


def test_schema_contains_full_action_enum():
    actions = (
        GitHubTool()
        .schema()["function"]["parameters"]["properties"]["action"]["enum"]
    )
    assert {
        "search_issues",
        "get_issue",
        "create_issue",
        "comment_issue",
        "close_issue",
        "list_pulls",
        "get_pull",
        "create_pull",
        "update_pull",
        "merge_pull",
        "review_pull",
        "request_review",
        "get_file",
        "list_workflow_runs",
        "get_workflow_run",
        "rerun_workflow",
    } == set(actions)


def test_unknown_action_returns_structured_error():
    tool = GitHubTool(credential_store=_store())
    result = tool.run(context=_ctx(), action="nope")
    assert result.metadata["error"] == "unsupported_action"
    assert "unsupported action" in result.text.lower()


def test_not_connected_when_no_credential_store():
    tool = GitHubTool()
    result = tool.run(context=ToolContext(prompt="x"), action="search_issues")
    assert result.metadata["connected"] is False
    assert "not connected" in result.text.lower()


def test_default_base_url_and_auth_scheme_fallback():
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(
            key="github",
            provider="github",
            secrets={"token": "ghp_test"},
            metadata={},
        )
    )
    tool = GitHubTool(credential_store=store)
    captured, fake = _capture({"items": [], "total_count": 0})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(context=_ctx(store), action="search_issues", query="bug")
    # After run the tool should have mutated the record to have defaults.
    record = store.get("github")
    assert record.metadata["base_url"] == "https://api.github.com"
    assert record.metadata["auth_scheme"] == "Bearer"


# ---------------------------------------------------------------- issues

def test_search_issues_happy_path():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "items": [
                {"number": 1, "state": "open", "title": "Crash on launch"},
                {"number": 2, "state": "open", "title": "Memory leak"},
            ],
            "total_count": 2,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="search_issues",
        query="is:issue is:open label:bug",
        per_page=10,
        page=1,
    )
    assert captured[0]["method"] == "GET"
    assert captured[0]["path"] == "/search/issues"
    assert captured[0]["query"]["q"] == "is:issue is:open label:bug"
    assert captured[0]["query"]["per_page"] == 10
    assert "Crash on launch" in out.text
    assert out.metadata["count"] == 2
    assert out.metadata["total_count"] == 2


def test_get_issue():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "number": 7,
            "state": "open",
            "title": "Issue",
            "user": {"login": "alice"},
            "labels": [{"name": "bug"}],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_issue",
        owner="octo",
        repo="demo",
        number=7,
    )
    assert captured[0]["path"] == "/repos/octo/demo/issues/7"
    assert "#7" in out.text
    assert "bug" in out.text


def test_create_issue_with_labels_and_assignees():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"number": 42, "title": "Report"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_issue",
        owner="octo",
        repo="demo",
        title="Report",
        body="Details",
        labels=["bug", "p1"],
        assignees=["alice"],
    )
    call = captured[0]
    assert call["method"] == "POST"
    assert call["path"] == "/repos/octo/demo/issues"
    assert call["body"]["title"] == "Report"
    assert call["body"]["labels"] == ["bug", "p1"]
    assert call["body"]["assignees"] == ["alice"]
    assert "#42" in out.text


def test_comment_issue():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"id": 999})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="comment_issue",
        owner="octo",
        repo="demo",
        number=7,
        body="looking into it",
    )
    assert captured[0]["method"] == "POST"
    assert captured[0]["path"] == "/repos/octo/demo/issues/7/comments"
    assert captured[0]["body"] == {"body": "looking into it"}
    assert "Comment added" in out.text


def test_close_issue():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"number": 7, "state": "closed"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="close_issue",
        owner="octo",
        repo="demo",
        number=7,
    )
    assert captured[0]["method"] == "PATCH"
    assert captured[0]["body"] == {"state": "closed"}
    assert "Closed issue #7" in out.text


# ---------------------------------------------------------------- pulls

def test_list_pulls():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        [
            {"number": 3, "state": "open", "title": "Fix"},
            {"number": 4, "state": "open", "title": "Refactor"},
        ]
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_pulls",
        owner="octo",
        repo="demo",
        state="open",
        per_page=25,
    )
    assert captured[0]["path"] == "/repos/octo/demo/pulls"
    assert captured[0]["query"] == {"state": "open", "per_page": 25}
    assert "#3" in out.text
    assert out.metadata["count"] == 2


def test_get_pull_shows_diff_summary_in_text():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "number": 10,
            "state": "open",
            "title": "Ship feature",
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
            "additions": 120,
            "deletions": 30,
            "changed_files": 7,
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_pull",
        owner="octo",
        repo="demo",
        number=10,
    )
    assert captured[0]["path"] == "/repos/octo/demo/pulls/10"
    assert "feature → main" in out.text
    assert "+120" in out.text
    assert "-30" in out.text
    assert "7 files" in out.text


def test_create_pull():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"number": 11, "title": "Ship"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="create_pull",
        owner="octo",
        repo="demo",
        title="Ship",
        head="feature",
        base="main",
        body="desc",
    )
    body = captured[0]["body"]
    assert body == {
        "title": "Ship",
        "head": "feature",
        "base": "main",
        "body": "desc",
    }
    assert "Pull request created" in out.text


def test_update_pull_partial_body_only():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"number": 11, "title": "t", "body": "updated"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="update_pull",
        owner="octo",
        repo="demo",
        number=11,
        body="updated",
    )
    call = captured[0]
    assert call["method"] == "PATCH"
    assert call["body"] == {"body": "updated"}
    assert "title" not in call["body"]
    assert "state" not in call["body"]
    assert out.metadata["updated_fields"] == ["body"]


def test_merge_pull_default_method_is_merge():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"merged": True, "message": "ok"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="merge_pull",
        owner="octo",
        repo="demo",
        number=11,
    )
    call = captured[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/repos/octo/demo/pulls/11/merge"
    assert call["body"] == {"merge_method": "merge"}
    assert out.metadata["merged"] is True


def test_merge_pull_squash():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"merged": True, "message": "ok"})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(_store()),
        action="merge_pull",
        owner="octo",
        repo="demo",
        number=11,
        merge_method="squash",
    )
    assert captured[0]["body"] == {"merge_method": "squash"}


def test_review_pull_approve_happy_path():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"id": 555, "state": "APPROVED"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="review_pull",
        owner="octo",
        repo="demo",
        number=11,
        event="APPROVE",
        body="LGTM",
    )
    call = captured[0]
    assert call["path"] == "/repos/octo/demo/pulls/11/reviews"
    assert call["body"] == {"event": "APPROVE", "body": "LGTM"}
    assert "APPROVE" in out.text


def test_review_pull_rejects_unknown_event_without_network_call():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"id": 1})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="review_pull",
        owner="octo",
        repo="demo",
        number=11,
        event="LGTM_PLZ",
    )
    assert out.metadata["error"] == "invalid_event"
    assert captured == []  # network never hit


def test_request_review():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({"number": 11})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="request_review",
        owner="octo",
        repo="demo",
        number=11,
        reviewers=["alice", "bob"],
    )
    call = captured[0]
    assert call["path"] == "/repos/octo/demo/pulls/11/requested_reviewers"
    assert call["body"] == {"reviewers": ["alice", "bob"]}
    assert "alice" in out.text


# ---------------------------------------------------------------- files

def test_get_file_base64_decode():
    tool = GitHubTool(credential_store=_store())
    encoded = base64.b64encode(b"hello world").decode("ascii")
    # GitHub often wraps base64 with newlines every 60 chars:
    wrapped = "\n".join(encoded[i : i + 4] for i in range(0, len(encoded), 4))
    captured, fake = _capture(
        {
            "encoding": "base64",
            "content": wrapped,
            "sha": "abc123",
            "size": 11,
            "download_url": "https://example.com/raw",
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file",
        owner="octo",
        repo="demo",
        path="README.md",
        ref="main",
    )
    assert captured[0]["path"] == "/repos/octo/demo/contents/README.md"
    assert captured[0]["query"] == {"ref": "main"}
    assert out.text == "hello world"
    assert out.metadata["sha"] == "abc123"


def test_get_file_unsupported_encoding_surfaces_download_url():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "encoding": "none",
            "download_url": "https://example.com/raw",
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_file",
        owner="octo",
        repo="demo",
        path="bin/blob",
    )
    assert out.metadata["error"] == "unsupported_encoding"
    assert out.metadata["download_url"] == "https://example.com/raw"
    assert "unsupported encoding" in out.text.lower()


# ---------------------------------------------------------------- actions

def test_list_workflow_runs():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 99,
                    "status": "completed",
                    "conclusion": "success",
                    "name": "CI",
                }
            ],
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="list_workflow_runs",
        owner="octo",
        repo="demo",
        per_page=5,
        page=1,
    )
    assert captured[0]["path"] == "/repos/octo/demo/actions/runs"
    assert captured[0]["query"] == {"per_page": 5, "page": 1}
    assert "99" in out.text
    assert out.metadata["total_count"] == 1


def test_get_workflow_run():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture(
        {
            "id": 99,
            "status": "completed",
            "conclusion": "failure",
            "name": "CI",
            "event": "push",
            "head_branch": "main",
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_workflow_run",
        owner="octo",
        repo="demo",
        run_id=99,
    )
    assert captured[0]["path"] == "/repos/octo/demo/actions/runs/99"
    assert "event=push" in out.text
    assert "failure" in out.text


def test_rerun_workflow():
    tool = GitHubTool(credential_store=_store())
    captured, fake = _capture({})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="rerun_workflow",
        owner="octo",
        repo="demo",
        run_id=99,
    )
    assert captured[0]["method"] == "POST"
    assert captured[0]["path"] == "/repos/octo/demo/actions/runs/99/rerun"
    assert "Re-run requested" in out.text


# ---------------------------------------------------------------- errors

def test_rate_limit_403_returns_retry_after_epoch():
    tool = GitHubTool(credential_store=_store())

    def raise_rate_limit(**_kwargs):
        raise _http_error(
            403,
            body=b'{"message":"API rate limit exceeded"}',
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1700000000",
            },
        )

    tool._request_json = raise_rate_limit  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="search_issues",
        query="q",
    )
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["retry_after_epoch"] == 1700000000
    assert out.metadata["status"] == 403


def test_other_http_error_surfaces_status_and_message():
    tool = GitHubTool(credential_store=_store())

    def raise_404(**_kwargs):
        raise _http_error(
            404,
            body=b'{"message":"Not Found"}',
            headers={},
        )

    tool._request_json = raise_404  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(_store()),
        action="get_issue",
        owner="octo",
        repo="demo",
        number=404,
    )
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 404
    assert out.metadata["message"] == "Not Found"
    assert "404" in out.text


# ---------------------------------------------------------------- pagination

def test_parse_next_url_with_real_link_header():
    header = (
        '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
        '<https://api.github.com/repositories/1/issues?page=5>; rel="last"'
    )
    assert (
        parse_next_url(header)
        == "https://api.github.com/repositories/1/issues?page=2"
    )


def test_parse_next_url_with_only_last_returns_none():
    header = '<https://api.github.com/repos/foo/bar/issues?page=5>; rel="last"'
    assert parse_next_url(header) is None


def test_parse_next_url_none_and_empty():
    assert parse_next_url(None) is None
    assert parse_next_url("") is None


# reference imports so pytest keeps them if linter wants them
assert pytest is not None
