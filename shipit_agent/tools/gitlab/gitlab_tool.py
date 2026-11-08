"""The ``gitlab`` tool: search GitLab issues, manage merge requests, read files, and control CI pipelines.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .http_helpers import _GitLabHTTP
from .issues import _IssueActions
from .merge_requests import _MergeRequestActions
from .prompt import GITLAB_PROMPT
from .repo_actions import _RepoActions


class GitLabTool(
    _GitLabHTTP,
    _IssueActions,
    _MergeRequestActions,
    _RepoActions,
    HTTPConnectorToolBase,
):
    """The ``gitlab`` tool: search GitLab issues, manage merge requests, read files, and control CI pipelines.
    """
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

    # ── actions ───────────────────────────────────────────────────

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
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

    # ── merge requests ────────────────────────────────────────────

    # ── repository files ──────────────────────────────────────────

    # ── pipelines ─────────────────────────────────────────────────
