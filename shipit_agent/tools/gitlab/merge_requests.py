"""GitLab merge request actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _MergeRequestActions:
    """GitLab merge request actions."""

    def _mr_line(self, item: dict[str, Any]) -> str:
        return (
            f"!{item.get('iid', '?')} [{item.get('state', '?')}] "
            f"{item.get('title', '')}  {item.get('web_url', '')}"
        )

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
