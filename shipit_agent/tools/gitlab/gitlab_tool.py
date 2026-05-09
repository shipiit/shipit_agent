from __future__ import annotations

import base64
import json
import urllib.error
from typing import Any
from urllib.parse import quote

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import GITLAB_PROMPT


class GitLabTool(HTTPConnectorToolBase):
    provider = "gitlab"

    def __init__(
        self,
        *,
        credential_key: str = "gitlab",
        credential_store=None,
        name: str = "gitlab",
        description: str = "Search GitLab issues, manage merge requests, read files, and control CI pipelines.",
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or GITLAB_PROMPT
        self.prompt_instructions = (
            "Use this for GitLab issue search, merge request management, file"
            " retrieval, and CI pipeline operations."
        )

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
                            "enum": [
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
                            ],
                            "default": "search_issues",
                        },
                        "query": {"type": "string"},
                        "project_id": {
                            "type": "string",
                            "description": "Numeric project id or URL path like 'myorg/myrepo'.",
                        },
                        "iid": {
                            "type": "integer",
                            "description": "In-project issue number (not the global GitLab id).",
                        },
                        "mr_iid": {
                            "type": "integer",
                            "description": "In-project merge request number.",
                        },
                        "pipeline_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "description_text": {"type": "string"},
                        "labels": {
                            "type": "string",
                            "description": "Comma-separated label names.",
                        },
                        "assignee_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "body": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": ["opened", "closed", "merged", "all"],
                            "default": "opened",
                        },
                        "source_branch": {"type": "string"},
                        "target_branch": {"type": "string"},
                        "path": {"type": "string"},
                        "ref": {"type": "string", "default": "main"},
                        "per_page": {"type": "integer", "default": 20},
                        "page": {"type": "integer", "default": 1},
                    },
                    "required": ["action"],
                },
            },
        }

    # ── base URL & helpers ────────────────────────────────────────

    def _base_url(self, record) -> str:
        return str(
            record.metadata.get("base_url")
            or record.secrets.get("base_url")
            or "https://gitlab.com"
        ).rstrip("/")

    @staticmethod
    def _encode_project_id(project_id: Any) -> str:
        pid = str(project_id).strip()
        if not pid:
            return ""
        if pid.isdigit():
            return pid
        return quote(pid, safe="")

    def _request_or_error(
        self,
        *,
        record,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        try:
            data = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return data, None
        except urllib.error.HTTPError as err:
            status = getattr(err, "code", 0)
            raw = ""
            try:
                raw = err.read().decode("utf-8", "ignore") if err.fp else ""
            except Exception:
                raw = ""
            if status == 429:
                retry_after = 0
                headers = getattr(err, "headers", None)
                if headers is not None:
                    value = headers.get("Retry-After") or headers.get("retry-after")
                    try:
                        retry_after = int(value) if value is not None else 0
                    except (TypeError, ValueError):
                        retry_after = 0
                return None, ToolOutput(
                    text=(
                        f"GitLab rate limit hit. Retry after {retry_after} seconds."
                    ),
                    metadata={
                        "provider": self.provider,
                        "connected": True,
                        "error": "rate_limited",
                        "status": status,
                        "retry_after_seconds": retry_after,
                    },
                )
            message = raw
            try:
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    message = (
                        parsed.get("message")
                        or parsed.get("error")
                        or parsed.get("error_description")
                        or raw
                    )
                    if isinstance(message, (dict, list)):
                        message = json.dumps(message)
            except ValueError:
                pass
            return None, ToolOutput(
                text=f"GitLab HTTP {status}: {message}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "http_error",
                    "status": status,
                    "message": message,
                },
            )

    # ── actions ───────────────────────────────────────────────────

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_issues")).strip().lower()

        if action == "search_issues":
            return self._search_issues(record, kwargs)
        if action == "get_issue":
            return self._get_issue(record, kwargs)
        if action == "create_issue":
            return self._create_issue(record, kwargs)
        if action == "close_issue":
            return self._close_issue(record, kwargs)
        if action == "comment_issue":
            return self._comment_issue(record, kwargs)
        if action == "list_merge_requests":
            return self._list_merge_requests(record, kwargs)
        if action == "get_merge_request":
            return self._get_merge_request(record, kwargs)
        if action == "create_merge_request":
            return self._create_merge_request(record, kwargs)
        if action == "merge_merge_request":
            return self._merge_merge_request(record, kwargs)
        if action == "approve_merge_request":
            return self._approve_merge_request(record, kwargs)
        if action == "comment_merge_request":
            return self._comment_merge_request(record, kwargs)
        if action == "get_file":
            return self._get_file(record, kwargs)
        if action == "list_pipelines":
            return self._list_pipelines(record, kwargs)
        if action == "get_pipeline":
            return self._get_pipeline(record, kwargs)
        if action == "retry_pipeline":
            return self._retry_pipeline(record, kwargs)
        if action == "cancel_pipeline":
            return self._cancel_pipeline(record, kwargs)

        return ToolOutput(
            text=f"Unsupported GitLab action: {action}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "unsupported_action",
                "action": action,
            },
        )

    # ── issues ────────────────────────────────────────────────────

    def _issue_line(self, item: dict[str, Any]) -> str:
        return (
            f"!{item.get('iid', '?')} [{item.get('state', '?')}] "
            f"{item.get('title', '')}  {item.get('web_url', '')}"
        )

    def _mr_line(self, item: dict[str, Any]) -> str:
        return (
            f"!{item.get('iid', '?')} [{item.get('state', '?')}] "
            f"{item.get('title', '')}  {item.get('web_url', '')}"
        )

    def _search_issues(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        query: dict[str, Any] = {
            "scope": "all",
            "search": str(kwargs.get("query", "")),
            "per_page": int(kwargs.get("per_page", 20)),
            "page": int(kwargs.get("page", 1)),
        }
        data, err = self._request_or_error(
            record=record, method="GET", path="/api/v4/issues", query=query
        )
        if err is not None:
            return err
        items = data if isinstance(data, list) else []
        return ToolOutput(
            text="\n".join(self._issue_line(item) for item in items)
            if items
            else "No GitLab issues found.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "search_issues",
                "items": items,
                "count": len(items),
            },
        )

    def _get_issue(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        iid = kwargs.get("iid")
        if not project_id or iid in (None, ""):
            return ToolOutput(
                text="project_id and iid are required for get_issue.",
                metadata={"provider": self.provider, "action": "get_issue"},
            )
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/issues/{iid}",
        )
        if err is not None:
            return err
        issue = data if isinstance(data, dict) else {}
        text = (
            f"!{issue.get('iid', iid)} [{issue.get('state', '?')}] "
            f"{issue.get('title', '')}\n"
            f"Author: {issue.get('author', {}).get('username', '?')}\n"
            f"URL: {issue.get('web_url', '')}\n"
            f"Description: {issue.get('description', '') or '(none)'}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "get_issue",
                "issue": issue,
            },
        )

    def _create_issue(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        title = str(kwargs.get("title", "")).strip()
        if not project_id or not title:
            return ToolOutput(
                text="project_id and title are required for create_issue.",
                metadata={"provider": self.provider, "action": "create_issue"},
            )
        body: dict[str, Any] = {
            "title": title,
            "description": str(kwargs.get("description_text", "")),
        }
        labels = kwargs.get("labels")
        if labels:
            body["labels"] = (
                labels if isinstance(labels, str) else ",".join(str(x) for x in labels)
            )
        assignee_ids = kwargs.get("assignee_ids")
        if assignee_ids:
            body["assignee_ids"] = list(assignee_ids)
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/issues",
            body=body,
        )
        if err is not None:
            return err
        issue = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=(
                f"GitLab issue created: !{issue.get('iid', '?')} "
                f"{issue.get('title', title)}  {issue.get('web_url', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "create_issue",
                "issue": issue,
            },
        )

    def _close_issue(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        iid = kwargs.get("iid")
        if not project_id or iid in (None, ""):
            return ToolOutput(
                text="project_id and iid are required for close_issue.",
                metadata={"provider": self.provider, "action": "close_issue"},
            )
        data, err = self._request_or_error(
            record=record,
            method="PUT",
            path=f"/api/v4/projects/{project_id}/issues/{iid}",
            body={"state_event": "close"},
        )
        if err is not None:
            return err
        issue = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=f"GitLab issue closed: !{issue.get('iid', iid)}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "close_issue",
                "issue": issue,
            },
        )

    def _comment_issue(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        iid = kwargs.get("iid")
        body_text = str(kwargs.get("body", "")).strip()
        if not project_id or iid in (None, "") or not body_text:
            return ToolOutput(
                text="project_id, iid, and body are required for comment_issue.",
                metadata={"provider": self.provider, "action": "comment_issue"},
            )
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/issues/{iid}/notes",
            body={"body": body_text},
        )
        if err is not None:
            return err
        note = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=f"Comment added to GitLab issue !{iid}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "comment_issue",
                "note": note,
            },
        )

    # ── merge requests ────────────────────────────────────────────

    def _list_merge_requests(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        if not project_id:
            return ToolOutput(
                text="project_id is required for list_merge_requests.",
                metadata={"provider": self.provider, "action": "list_merge_requests"},
            )
        query = {
            "state": str(kwargs.get("state", "opened")),
            "per_page": int(kwargs.get("per_page", 20)),
            "page": int(kwargs.get("page", 1)),
        }
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/merge_requests",
            query=query,
        )
        if err is not None:
            return err
        items = data if isinstance(data, list) else []
        return ToolOutput(
            text="\n".join(self._mr_line(item) for item in items)
            if items
            else "No GitLab merge requests found.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "list_merge_requests",
                "items": items,
                "count": len(items),
            },
        )

    def _get_merge_request(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        mr_iid = kwargs.get("mr_iid")
        if not project_id or mr_iid in (None, ""):
            return ToolOutput(
                text="project_id and mr_iid are required for get_merge_request.",
                metadata={"provider": self.provider, "action": "get_merge_request"},
            )
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
        )
        if err is not None:
            return err
        mr = data if isinstance(data, dict) else {}
        text = (
            f"!{mr.get('iid', mr_iid)} [{mr.get('state', '?')}] "
            f"{mr.get('title', '')}\n"
            f"Source: {mr.get('source_branch', '?')} -> "
            f"Target: {mr.get('target_branch', '?')}\n"
            f"Author: {mr.get('author', {}).get('username', '?')}\n"
            f"URL: {mr.get('web_url', '')}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "get_merge_request",
                "merge_request": mr,
            },
        )

    def _create_merge_request(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        source_branch = str(kwargs.get("source_branch", "")).strip()
        target_branch = str(kwargs.get("target_branch", "")).strip()
        title = str(kwargs.get("title", "")).strip()
        if not project_id or not source_branch or not target_branch or not title:
            return ToolOutput(
                text=(
                    "project_id, source_branch, target_branch, and title are"
                    " required for create_merge_request."
                ),
                metadata={
                    "provider": self.provider,
                    "action": "create_merge_request",
                },
            )
        body = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": str(kwargs.get("description_text", "")),
        }
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/merge_requests",
            body=body,
        )
        if err is not None:
            return err
        mr = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=(
                f"GitLab merge request created: !{mr.get('iid', '?')} "
                f"{mr.get('title', title)}  {mr.get('web_url', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "create_merge_request",
                "merge_request": mr,
            },
        )

    def _merge_merge_request(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        mr_iid = kwargs.get("mr_iid")
        if not project_id or mr_iid in (None, ""):
            return ToolOutput(
                text="project_id and mr_iid are required for merge_merge_request.",
                metadata={"provider": self.provider, "action": "merge_merge_request"},
            )
        data, err = self._request_or_error(
            record=record,
            method="PUT",
            path=f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/merge",
        )
        if err is not None:
            return err
        mr = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=f"GitLab MR merged: !{mr.get('iid', mr_iid)} [{mr.get('state', '?')}]",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "merge_merge_request",
                "merge_request": mr,
            },
        )

    def _approve_merge_request(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        mr_iid = kwargs.get("mr_iid")
        if not project_id or mr_iid in (None, ""):
            return ToolOutput(
                text="project_id and mr_iid are required for approve_merge_request.",
                metadata={"provider": self.provider, "action": "approve_merge_request"},
            )
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/approve",
        )
        if err is not None:
            return err
        result = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=f"GitLab MR approved: !{mr_iid}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "approve_merge_request",
                "result": result,
            },
        )

    def _comment_merge_request(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        mr_iid = kwargs.get("mr_iid")
        body_text = str(kwargs.get("body", "")).strip()
        if not project_id or mr_iid in (None, "") or not body_text:
            return ToolOutput(
                text=(
                    "project_id, mr_iid, and body are required for"
                    " comment_merge_request."
                ),
                metadata={
                    "provider": self.provider,
                    "action": "comment_merge_request",
                },
            )
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            body={"body": body_text},
        )
        if err is not None:
            return err
        note = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=f"Comment added to GitLab MR !{mr_iid}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "comment_merge_request",
                "note": note,
            },
        )

    # ── repository files ──────────────────────────────────────────

    def _get_file(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        path = str(kwargs.get("path", "")).strip()
        ref = str(kwargs.get("ref", "main")).strip() or "main"
        if not project_id or not path:
            return ToolOutput(
                text="project_id and path are required for get_file.",
                metadata={"provider": self.provider, "action": "get_file"},
            )
        encoded_path = quote(path, safe="")
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/repository/files/{encoded_path}",
            query={"ref": ref},
        )
        if err is not None:
            return err
        file_data = data if isinstance(data, dict) else {}
        content_raw = file_data.get("content", "")
        encoding = str(file_data.get("encoding", "")).lower()
        decoded = ""
        if content_raw and encoding == "base64":
            try:
                decoded = base64.b64decode(content_raw).decode("utf-8", "replace")
            except Exception:
                decoded = ""
        else:
            decoded = str(content_raw)
        return ToolOutput(
            text=decoded
            if decoded
            else f"(empty file at {path}@{ref})",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "get_file",
                "file": {
                    "path": path,
                    "ref": ref,
                    "encoding": encoding,
                    "content": decoded,
                    "raw": file_data,
                },
            },
        )

    # ── pipelines ─────────────────────────────────────────────────

    def _pipeline_line(self, item: dict[str, Any]) -> str:
        return (
            f"#{item.get('id', '?')} [{item.get('status', '?')}] "
            f"ref={item.get('ref', '?')} sha={str(item.get('sha', ''))[:8]} "
            f"{item.get('web_url', '')}"
        )

    def _list_pipelines(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        if not project_id:
            return ToolOutput(
                text="project_id is required for list_pipelines.",
                metadata={"provider": self.provider, "action": "list_pipelines"},
            )
        query = {
            "per_page": int(kwargs.get("per_page", 20)),
            "page": int(kwargs.get("page", 1)),
        }
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/pipelines",
            query=query,
        )
        if err is not None:
            return err
        items = data if isinstance(data, list) else []
        return ToolOutput(
            text="\n".join(self._pipeline_line(item) for item in items)
            if items
            else "No GitLab pipelines found.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "list_pipelines",
                "items": items,
                "count": len(items),
            },
        )

    def _get_pipeline(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        pipeline_id = kwargs.get("pipeline_id")
        if not project_id or pipeline_id in (None, ""):
            return ToolOutput(
                text="project_id and pipeline_id are required for get_pipeline.",
                metadata={"provider": self.provider, "action": "get_pipeline"},
            )
        data, err = self._request_or_error(
            record=record,
            method="GET",
            path=f"/api/v4/projects/{project_id}/pipelines/{pipeline_id}",
        )
        if err is not None:
            return err
        pipeline = data if isinstance(data, dict) else {}
        text = (
            f"#{pipeline.get('id', pipeline_id)} [{pipeline.get('status', '?')}]\n"
            f"Ref: {pipeline.get('ref', '?')}\n"
            f"SHA: {pipeline.get('sha', '?')}\n"
            f"URL: {pipeline.get('web_url', '')}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "get_pipeline",
                "pipeline": pipeline,
            },
        )

    def _retry_pipeline(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        pipeline_id = kwargs.get("pipeline_id")
        if not project_id or pipeline_id in (None, ""):
            return ToolOutput(
                text="project_id and pipeline_id are required for retry_pipeline.",
                metadata={"provider": self.provider, "action": "retry_pipeline"},
            )
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/pipelines/{pipeline_id}/retry",
        )
        if err is not None:
            return err
        pipeline = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=(
                f"GitLab pipeline retried: #{pipeline.get('id', pipeline_id)} "
                f"[{pipeline.get('status', '?')}]"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "retry_pipeline",
                "pipeline": pipeline,
            },
        )

    def _cancel_pipeline(self, record, kwargs: dict[str, Any]) -> ToolOutput:
        project_id = self._encode_project_id(kwargs.get("project_id", ""))
        pipeline_id = kwargs.get("pipeline_id")
        if not project_id or pipeline_id in (None, ""):
            return ToolOutput(
                text="project_id and pipeline_id are required for cancel_pipeline.",
                metadata={"provider": self.provider, "action": "cancel_pipeline"},
            )
        data, err = self._request_or_error(
            record=record,
            method="POST",
            path=f"/api/v4/projects/{project_id}/pipelines/{pipeline_id}/cancel",
        )
        if err is not None:
            return err
        pipeline = data if isinstance(data, dict) else {}
        return ToolOutput(
            text=(
                f"GitLab pipeline cancelled: #{pipeline.get('id', pipeline_id)} "
                f"[{pipeline.get('status', '?')}]"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": "cancel_pipeline",
                "pipeline": pipeline,
            },
        )
