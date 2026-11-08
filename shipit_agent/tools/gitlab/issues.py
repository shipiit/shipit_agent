"""GitLab issue actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _IssueActions:
    """GitLab issue actions."""

    def _issue_line(self, item: dict[str, Any]) -> str:
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
