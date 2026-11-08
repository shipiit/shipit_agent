"""Figma comment, project and component actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _CommentTeamActions:
    """Figma comment, project and component actions."""

    def _get_comments(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        file_key = str(parts["file_key"]).strip()
        path = f"/v1/files/{file_key}/comments"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        comments = data.get("comments", []) if isinstance(data, dict) else []
        lines = [
            (
                f"{c.get('id', '?')} "
                f"[{c.get('user', {}).get('handle', '?')}]: "
                f"{c.get('message', '')}"
            )
            for c in comments
        ]
        text = "\n".join(lines) if lines else "No comments on this Figma file."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "items": comments,
                "count": len(comments),
            },
        )

    def _post_comment(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        message = str(kwargs.get("message", "")).strip()
        if not message:
            return ToolOutput(
                text="Figma: `message` is required for post_comment.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["message"],
                },
            )
        file_key = str(parts["file_key"]).strip()
        body: dict[str, Any] = {"message": message}
        client_meta = kwargs.get("client_meta")
        if isinstance(client_meta, dict) and client_meta:
            body["client_meta"] = client_meta
        path = f"/v1/files/{file_key}/comments"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        comment = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Comment posted on Figma file {file_key} "
                f"(id={comment.get('id', '?')})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "item": comment,
            },
        )

    def _resolve_comment(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key", "comment_id")
        if err is not None:
            return err
        file_key = str(parts["file_key"]).strip()
        comment_id = str(parts["comment_id"]).strip()
        path = f"/v1/files/{file_key}/comments/{comment_id}"
        payload, err = self._request_or_error(
            record=record, method="DELETE", path=path
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=f"Resolved Figma comment {comment_id} on file {file_key}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "comment_id": comment_id,
                "item": data,
            },
        )

    def _get_team_projects(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "team_id")
        if err is not None:
            return err
        team_id = str(parts["team_id"]).strip()
        path = f"/v1/teams/{team_id}/projects"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        projects = data.get("projects", []) if isinstance(data, dict) else []
        lines = [
            f"{p.get('id', '?')}: {p.get('name', '')}" for p in projects
        ]
        text = (
            "\n".join(lines)
            if lines
            else f"No projects found for Figma team {team_id}."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "team_id": team_id,
                "items": projects,
                "count": len(projects),
            },
        )

    def _get_project_files(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "project_id")
        if err is not None:
            return err
        project_id = str(parts["project_id"]).strip()
        path = f"/v1/projects/{project_id}/files"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        files = data.get("files", []) if isinstance(data, dict) else []
        lines = [
            (
                f"{f.get('key', '?')}: {f.get('name', '')} "
                f"(last_modified={f.get('last_modified', '?')})"
            )
            for f in files
        ]
        text = (
            "\n".join(lines)
            if lines
            else f"No files found in Figma project {project_id}."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "project_id": project_id,
                "items": files,
                "count": len(files),
            },
        )

    def _get_team_components(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "team_id")
        if err is not None:
            return err
        team_id = str(parts["team_id"]).strip()
        path = f"/v1/teams/{team_id}/components"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        components = (
            meta.get("components", []) if isinstance(meta, dict) else []
        )
        if not components and isinstance(data, dict):
            # Some shapes return components at top-level
            components = data.get("components", []) or components
        lines = [
            (
                f"{c.get('key', '?')}: {c.get('name', '')} "
                f"({c.get('node_id', '?')})"
            )
            for c in components
        ]
        text = (
            "\n".join(lines)
            if lines
            else f"No components found for Figma team {team_id}."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "team_id": team_id,
                "items": components,
                "count": len(components),
            },
        )
