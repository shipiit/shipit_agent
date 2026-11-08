"""GitHub file and Actions workflow-run actions."""

from __future__ import annotations

import base64
from typing import Any

from shipit_agent.tools.base import ToolOutput


class _RepoActions:
    """GitHub file and Actions workflow-run actions."""

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
