"""GitLab file and pipeline actions."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput


class _RepoActions:
    """GitLab file and pipeline actions."""

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
