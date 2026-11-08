"""GitHub issue actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _IssueActions:
    """GitHub issue actions."""

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
