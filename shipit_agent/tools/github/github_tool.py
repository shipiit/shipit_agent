"""The ``github`` tool: work with GitHub issues, pull requests, file contents, and Actions workflow runs via the REST API.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .constants import (
    _VALID_MERGE_METHODS,
    _VALID_REVIEW_EVENTS,
)
from .http_helpers import _GitHubHTTP
from .issues import _IssueActions
from .prompt import GITHUB_PROMPT
from .pulls import _PullActions
from .repo_actions import _RepoActions
from .reviews import _ReviewActions

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


class GitHubTool(
    _GitHubHTTP,
    _IssueActions,
    _PullActions,
    _ReviewActions,
    _RepoActions,
    HTTPConnectorToolBase,
):
    """The ``github`` tool: work with GitHub issues, pull requests, file contents, and Actions workflow runs via the REST API.
    """
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

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
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
