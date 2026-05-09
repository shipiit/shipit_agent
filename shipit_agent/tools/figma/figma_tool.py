from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import FIGMA_PROMPT


_DEFAULT_BASE_URL = "https://api.figma.com"
_VALID_IMAGE_FORMATS = {"png", "jpg", "svg", "pdf"}

_ACTIONS = [
    "get_file",
    "get_file_nodes",
    "get_image",
    "get_comments",
    "post_comment",
    "resolve_comment",
    "get_team_projects",
    "get_project_files",
    "get_team_components",
]


class FigmaTool(HTTPConnectorToolBase):
    provider = "figma"

    def __init__(
        self,
        *,
        credential_key: str = "figma",
        credential_store: Any = None,
        name: str = "figma",
        description: str = (
            "Read Figma files, render node images, browse and post comments, and "
            "introspect team projects / components via the Figma REST API."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or FIGMA_PROMPT
        self.prompt_instructions = (
            "Use this for reading Figma file structure, rendering node images, "
            "managing design-review comments, and browsing team / project / "
            "component libraries."
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
                            "default": "get_file",
                        },
                        "file_key": {"type": "string"},
                        "team_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "comment_id": {"type": "string"},
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "format": {
                            "type": "string",
                            "enum": sorted(_VALID_IMAGE_FORMATS),
                            "default": "png",
                        },
                        "scale": {"type": "number", "default": 1},
                        "message": {"type": "string"},
                        "client_meta": {
                            "type": "object",
                            "description": (
                                "Either {'node_id': str, 'node_offset': {'x': n, 'y': n}} "
                                "or {'x': n, 'y': n} to pin a comment."
                            ),
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------ auth

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        headers = super()._headers(record)
        headers.pop("authorization", None)
        token = (record.secrets or {}).get("token") or (record.secrets or {}).get(
            "access_token"
        )
        if token:
            headers["x-figma-token"] = str(token)
        return headers

    # --------------------------------------------------------------- base URL

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.figma.com if not already set."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get("base_url"):
            metadata["base_url"] = _DEFAULT_BASE_URL
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
                text=f"Figma request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        headers = getattr(err, "headers", None)
        retry_after = None
        if headers is not None:
            try:
                retry_after = headers.get("Retry-After")
            except Exception:  # pragma: no cover - defensive
                retry_after = None
        if err.code == 429:
            retry_after_seconds = 0
            try:
                retry_after_seconds = int(retry_after) if retry_after is not None else 0
            except (TypeError, ValueError):
                retry_after_seconds = 0
            return ToolOutput(
                text=(
                    "Figma rate limit exceeded. Retry after "
                    f"{retry_after_seconds} seconds."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after_seconds": retry_after_seconds,
                    "status": 429,
                },
            )

        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"Figma HTTP {err.code}: {message}",
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
                if isinstance(parsed, dict):
                    msg = parsed.get("err") or parsed.get("message")
                    if isinstance(msg, str) and msg:
                        return msg
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    # ------------------------------------------------------------- utilities

    @staticmethod
    def _require(
        kwargs: dict[str, Any], *names: str
    ) -> tuple[dict[str, Any], ToolOutput | None]:
        missing = [n for n in names if not str(kwargs.get(n, "")).strip()]
        if missing:
            return {}, ToolOutput(
                text=f"Figma: missing required parameter(s) {', '.join(missing)}.",
                metadata={
                    "provider": "figma",
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

        action = str(kwargs.get("action", "get_file")).strip()

        handlers = {
            "get_file": self._get_file,
            "get_file_nodes": self._get_file_nodes,
            "get_image": self._get_image,
            "get_comments": self._get_comments,
            "post_comment": self._post_comment,
            "resolve_comment": self._resolve_comment,
            "get_team_projects": self._get_team_projects,
            "get_project_files": self._get_project_files,
            "get_team_components": self._get_team_components,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Figma: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ------------------------------------------------------------- actions

    def _get_file(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        file_key = str(parts["file_key"]).strip()
        path = f"/v1/files/{file_key}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        document = data.get("document", {}) if isinstance(data, dict) else {}
        pages = document.get("children", []) if isinstance(document, dict) else []
        name = data.get("name", "(untitled)")
        last_modified = data.get("lastModified", "?")
        text = (
            f"Figma file: {name}\n"
            f"  last_modified: {last_modified}\n"
            f"  pages: {len(pages)}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "file": data,
            },
        )

    def _get_file_nodes(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        ids = kwargs.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return ToolOutput(
                text="Figma: `ids` must be a non-empty list for get_file_nodes.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["ids"],
                },
            )
        file_key = str(parts["file_key"]).strip()
        query = {"ids": ",".join(str(i) for i in ids)}
        path = f"/v1/files/{file_key}/nodes"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        nodes = data.get("nodes", {}) if isinstance(data, dict) else {}
        found_ids = list(nodes.keys()) if isinstance(nodes, dict) else []
        lines = [f"{nid}: present" for nid in found_ids] or [
            "No nodes returned for the given ids."
        ]
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "ids": [str(i) for i in ids],
                "nodes": nodes,
                "count": len(found_ids),
            },
        )

    def _get_image(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        ids = kwargs.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return ToolOutput(
                text="Figma: `ids` must be a non-empty list for get_image.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["ids"],
                },
            )
        fmt = str(kwargs.get("format") or "png").strip().lower()
        if fmt not in _VALID_IMAGE_FORMATS:
            return ToolOutput(
                text=(
                    f"Figma: unsupported image format '{fmt}' "
                    "(expected one of png|jpg|svg|pdf)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_format",
                    "format": fmt,
                },
            )
        try:
            scale = float(kwargs.get("scale", 1) or 1)
        except (TypeError, ValueError):
            scale = 1.0
        file_key = str(parts["file_key"]).strip()
        body = {
            "ids": ",".join(str(i) for i in ids),
            "format": fmt,
            "scale": scale,
        }
        path = f"/v1/images/{file_key}"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        images = data.get("images", {}) if isinstance(data, dict) else {}
        lines = [
            f"{node_id}: {url or '(no url)'}"
            for node_id, url in (images.items() if isinstance(images, dict) else [])
        ]
        text = (
            "\n".join(lines)
            if lines
            else "No rendered images returned for the given ids."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "format": fmt,
                "scale": scale,
                "images": images,
                "count": len(lines),
            },
        )

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
