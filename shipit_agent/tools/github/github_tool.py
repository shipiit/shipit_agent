from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import GITHUB_PROMPT


_DEFAULT_BASE_URL = "https://api.github.com"
_DEFAULT_AUTH_SCHEME = "Bearer"
_VALID_REVIEW_EVENTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}
_VALID_MERGE_METHODS = {"merge", "squash", "rebase"}

_ACTIONS = [
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
]


class GitHubTool(HTTPConnectorToolBase):
    provider = "github"

    def __init__(
        self,
        *,
        credential_key: str = "github",
        credential_store: Any = None,
        name: str = "github",
        description: str = (
            "Work with GitHub issues, pull requests, file contents, and "
            "Actions workflow runs via the REST API."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or GITHUB_PROMPT
        self.prompt_instructions = (
            "Use this for GitHub issue triage, pull request review and merging, "
            "reading source files, and managing GitHub Actions workflow runs."
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
                            "default": "search_issues",
                        },
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "number": {"type": "integer"},
                        "run_id": {"type": "integer"},
                        "query": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "state": {"type": "string"},
                        "head": {"type": "string"},
                        "base": {"type": "string"},
                        "path": {"type": "string"},
                        "ref": {"type": "string"},
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "assignees": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "reviewers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "merge_method": {
                            "type": "string",
                            "enum": sorted(_VALID_MERGE_METHODS),
                            "default": "merge",
                        },
                        "event": {
                            "type": "string",
                            "enum": sorted(_VALID_REVIEW_EVENTS),
                        },
                        "per_page": {"type": "integer", "default": 30},
                        "page": {"type": "integer", "default": 1},
                    },
                    "required": ["action"],
                },
            },
        }

    # --------------------------------------------------------------- base URL

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.github.com and auth_scheme to Bearer."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get("base_url"):
            metadata["base_url"] = _DEFAULT_BASE_URL
        if not metadata.get("auth_scheme"):
            metadata["auth_scheme"] = _DEFAULT_AUTH_SCHEME
        record.metadata = metadata
        return record

    # ---------------------------------------------------------- HTTP wrapper

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        """Call _request_json; return (payload, None) on success, (None, error_out) on failure."""
        try:
            payload = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"GitHub request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        headers = getattr(err, "headers", None)
        remaining = None
        reset = None
        if headers is not None:
            try:
                remaining = headers.get("X-RateLimit-Remaining")
                reset = headers.get("X-RateLimit-Reset")
            except Exception:  # pragma: no cover - defensive
                remaining = None
                reset = None
        if err.code == 403 and remaining is not None and str(remaining) == "0":
            retry_after_epoch = 0
            try:
                retry_after_epoch = int(reset) if reset is not None else 0
            except (TypeError, ValueError):
                retry_after_epoch = 0
            return ToolOutput(
                text=(
                    "GitHub rate limit exceeded. Retry after epoch "
                    f"{retry_after_epoch}."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after_epoch": retry_after_epoch,
                    "status": 403,
                },
            )

        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"GitHub HTTP {err.code}: {message}",
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
                msg = parsed.get("message")
                if isinstance(msg, str) and msg:
                    return msg
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    # ------------------------------------------------------------- utilities

    @staticmethod
    def _require(kwargs: dict[str, Any], *names: str) -> tuple[dict[str, Any], ToolOutput | None]:
        missing = [n for n in names if not str(kwargs.get(n, "")).strip()]
        if missing:
            return {}, ToolOutput(
                text=f"GitHub: missing required parameter(s) {', '.join(missing)}.",
                metadata={
                    "provider": "github",
                    "error": "missing_parameter",
                    "missing": missing,
                },
            )
        return {n: kwargs.get(n) for n in names}, None

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        record = self._ensure_base_url(record)

        action = str(kwargs.get("action", "search_issues")).strip()

        handlers = {
            "search_issues": self._search_issues,
            "get_issue": self._get_issue,
            "create_issue": self._create_issue,
            "comment_issue": self._comment_issue,
            "close_issue": self._close_issue,
            "list_pulls": self._list_pulls,
            "get_pull": self._get_pull,
            "create_pull": self._create_pull,
            "update_pull": self._update_pull,
            "merge_pull": self._merge_pull,
            "review_pull": self._review_pull,
            "request_review": self._request_review,
            "get_file": self._get_file,
            "list_workflow_runs": self._list_workflow_runs,
            "get_workflow_run": self._get_workflow_run,
            "rerun_workflow": self._rerun_workflow,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"GitHub: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ------------------------------------------------------------- actions

    def _search_issues(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="GitHub: `query` is required for search_issues.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        query_params: dict[str, Any] = {"q": q}
        if kwargs.get("per_page") is not None:
            query_params["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query_params["page"] = int(kwargs["page"])
        payload, err = self._request_or_error(
            record=record, method="GET", path="/search/issues", query=query_params
        )
        if err is not None:
            return err
        items = payload.get("items", []) if isinstance(payload, dict) else []
        lines = [
            f"#{item.get('number', '?')} [{item.get('state', '?')}] {item.get('title', '')}"
            for item in items
        ]
        text = "\n".join(lines) if lines else "No GitHub issues matched the query."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": items,
                "count": len(items),
                "total_count": payload.get("total_count") if isinstance(payload, dict) else None,
            },
        )

    def _get_issue(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for get_issue.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/issues/{int(number)}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        issue = payload if isinstance(payload, dict) else {}
        text = (
            f"#{issue.get('number', number)} [{issue.get('state', '?')}] "
            f"{issue.get('title', '')}\n"
            f"By: {issue.get('user', {}).get('login', '?')}  "
            f"Labels: {', '.join(label.get('name', '') for label in issue.get('labels', [])) or 'none'}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": issue,
            },
        )

    def _create_issue(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo", "title")
        if err is not None:
            return err
        body_payload: dict[str, Any] = {"title": str(kwargs.get("title", ""))}
        if kwargs.get("body") is not None:
            body_payload["body"] = str(kwargs.get("body"))
        labels = kwargs.get("labels")
        if isinstance(labels, list) and labels:
            body_payload["labels"] = [str(label) for label in labels]
        assignees = kwargs.get("assignees")
        if isinstance(assignees, list) and assignees:
            body_payload["assignees"] = [str(a) for a in assignees]
        path = f"/repos/{parts['owner']}/{parts['repo']}/issues"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body_payload
        )
        if err is not None:
            return err
        issue = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"GitHub issue created: #{issue.get('number', '?')} "
                f"{issue.get('title', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": issue,
            },
        )

    def _comment_issue(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for comment_issue.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        body_text = str(kwargs.get("body", "")).strip()
        if not body_text:
            return ToolOutput(
                text="GitHub: `body` is required for comment_issue.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/issues/{int(number)}/comments"
        )
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body={"body": body_text}
        )
        if err is not None:
            return err
        comment = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=f"Comment added to issue #{int(number)} (id={comment.get('id', '?')}).",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": comment,
            },
        )

    def _close_issue(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for close_issue.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/issues/{int(number)}"
        payload, err = self._request_or_error(
            record=record, method="PATCH", path=path, body={"state": "closed"}
        )
        if err is not None:
            return err
        issue = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=f"Closed issue #{int(number)} ({issue.get('state', 'closed')}).",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": issue,
            },
        )

    def _list_pulls(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        state = str(kwargs.get("state", "open")).strip() or "open"
        query: dict[str, Any] = {"state": state}
        if kwargs.get("per_page") is not None:
            query["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query["page"] = int(kwargs["page"])
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        items = payload if isinstance(payload, list) else []
        lines = [
            f"#{item.get('number', '?')} [{item.get('state', '?')}] {item.get('title', '')}"
            for item in items
        ]
        text = "\n".join(lines) if lines else "No GitHub pull requests found."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": items,
                "count": len(items),
            },
        )

    def _get_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for get_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        head = pr.get("head", {}).get("ref", "?")
        base = pr.get("base", {}).get("ref", "?")
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        changed = pr.get("changed_files", 0)
        text = (
            f"#{pr.get('number', number)} [{pr.get('state', '?')}] "
            f"{pr.get('title', '')}\n"
            f"  {head} → {base}  (+{additions}/-{deletions} across {changed} files)"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
            },
        )

    def _create_pull(self, *, record, action, kwargs):
        parts, err = self._require(
            kwargs, "owner", "repo", "title", "head", "base"
        )
        if err is not None:
            return err
        body_payload: dict[str, Any] = {
            "title": str(kwargs.get("title", "")),
            "head": str(kwargs.get("head", "")),
            "base": str(kwargs.get("base", "")),
        }
        if kwargs.get("body") is not None:
            body_payload["body"] = str(kwargs.get("body"))
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body_payload
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Pull request created: #{pr.get('number', '?')} "
                f"{pr.get('title', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
            },
        )

    def _update_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for update_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        body_payload: dict[str, Any] = {}
        for field in ("title", "body", "state"):
            if kwargs.get(field) is not None:
                body_payload[field] = str(kwargs.get(field))
        if not body_payload:
            return ToolOutput(
                text="GitHub: update_pull requires at least one of title/body/state.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}"
        payload, err = self._request_or_error(
            record=record, method="PATCH", path=path, body=body_payload
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Pull request #{int(number)} updated "
                f"({', '.join(body_payload.keys())})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
                "updated_fields": sorted(body_payload.keys()),
            },
        )

    def _merge_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for merge_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        merge_method = str(kwargs.get("merge_method", "merge")).strip() or "merge"
        if merge_method not in _VALID_MERGE_METHODS:
            return ToolOutput(
                text=(
                    "GitHub: unsupported merge_method "
                    f"'{merge_method}' (expected one of merge|squash|rebase)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_merge_method",
                    "merge_method": merge_method,
                },
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}/merge"
        )
        payload, err = self._request_or_error(
            record=record,
            method="PUT",
            path=path,
            body={"merge_method": merge_method},
        )
        if err is not None:
            return err
        result = payload if isinstance(payload, dict) else {}
        merged = bool(result.get("merged"))
        return ToolOutput(
            text=(
                f"Pull request #{int(number)} "
                f"{'merged' if merged else 'merge attempt returned'} "
                f"({merge_method}): {result.get('message', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "merge_method": merge_method,
                "merged": merged,
                "item": result,
            },
        )

    def _review_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for review_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        event = str(kwargs.get("event", "")).strip().upper()
        if event not in _VALID_REVIEW_EVENTS:
            return ToolOutput(
                text=(
                    "GitHub: unsupported review event "
                    f"'{event or '(missing)'}' "
                    "(expected one of APPROVE|REQUEST_CHANGES|COMMENT)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_event",
                    "event": event,
                },
            )
        body_payload: dict[str, Any] = {"event": event}
        if kwargs.get("body") is not None:
            body_payload["body"] = str(kwargs.get("body"))
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}/reviews"
        )
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body_payload
        )
        if err is not None:
            return err
        review = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Review submitted on PR #{int(number)}: {event} "
                f"(id={review.get('id', '?')})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "event": event,
                "item": review,
            },
        )

    def _request_review(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for request_review.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        reviewers = kwargs.get("reviewers") or []
        if not isinstance(reviewers, list) or not reviewers:
            return ToolOutput(
                text="GitHub: `reviewers` must be a non-empty list for request_review.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/"
            f"{int(number)}/requested_reviewers"
        )
        payload, err = self._request_or_error(
            record=record,
            method="POST",
            path=path,
            body={"reviewers": [str(r) for r in reviewers]},
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Requested review on PR #{int(number)} from "
                f"{', '.join(str(r) for r in reviewers)}."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "reviewers": list(reviewers),
                "item": pr,
            },
        )

    def _get_file(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo", "path")
        if err is not None:
            return err
        query: dict[str, Any] = {}
        ref = kwargs.get("ref")
        if ref:
            query["ref"] = str(ref)
        file_path = str(kwargs.get("path", "")).lstrip("/")
        path = f"/repos/{parts['owner']}/{parts['repo']}/contents/{file_path}"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query or None
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        encoding = data.get("encoding")
        if encoding != "base64":
            return ToolOutput(
                text=(
                    f"GitHub file '{file_path}' uses unsupported encoding "
                    f"'{encoding}'. Use download_url to fetch raw bytes."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "error": "unsupported_encoding",
                    "encoding": encoding,
                    "download_url": data.get("download_url"),
                    "item": data,
                },
            )
        raw = data.get("content", "") or ""
        try:
            decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception as exc:
            return ToolOutput(
                text=f"GitHub: failed to base64-decode file '{file_path}': {exc}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "error": "decode_failed",
                    "download_url": data.get("download_url"),
                },
            )
        return ToolOutput(
            text=decoded,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "path": file_path,
                "sha": data.get("sha"),
                "size": data.get("size"),
                "download_url": data.get("download_url"),
            },
        )

    def _list_workflow_runs(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        query: dict[str, Any] = {}
        if kwargs.get("per_page") is not None:
            query["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query["page"] = int(kwargs["page"])
        path = f"/repos/{parts['owner']}/{parts['repo']}/actions/runs"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query or None
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        runs = data.get("workflow_runs", []) or []
        lines = [
            f"{run.get('id', '?')} [{run.get('status', '?')}/{run.get('conclusion', '?')}] {run.get('name', '')}"
            for run in runs
        ]
        text = "\n".join(lines) if lines else "No workflow runs found."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": runs,
                "count": len(runs),
                "total_count": data.get("total_count"),
            },
        )

    def _get_workflow_run(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        run_id = kwargs.get("run_id")
        if run_id is None:
            return ToolOutput(
                text="GitHub: `run_id` is required for get_workflow_run.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/actions/runs/{int(run_id)}"
        )
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        run = payload if isinstance(payload, dict) else {}
        text = (
            f"Run {run.get('id', run_id)} [{run.get('status', '?')}/"
            f"{run.get('conclusion', '?')}] {run.get('name', '')}\n"
            f"  event={run.get('event', '?')} branch={run.get('head_branch', '?')}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": run,
            },
        )

    def _rerun_workflow(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        run_id = kwargs.get("run_id")
        if run_id is None:
            return ToolOutput(
                text="GitHub: `run_id` is required for rerun_workflow.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/actions/runs/"
            f"{int(run_id)}/rerun"
        )
        payload, err = self._request_or_error(record=record, method="POST", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=f"Re-run requested for workflow run {int(run_id)}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "run_id": int(run_id),
                "item": data,
            },
        )


