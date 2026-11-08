"""GitLab REST plumbing: base URL, project ids and requests."""

from __future__ import annotations

import json
import urllib.error
from typing import Any
from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput


class _GitLabHTTP:
    """GitLab REST plumbing: base URL, project ids and requests."""

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
