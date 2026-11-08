"""Figma REST plumbing: headers, requests and error output."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput

from .constants import _DEFAULT_BASE_URL


class _FigmaHTTP:
    """Figma REST plumbing: headers, requests and error output."""

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        headers = super()._headers(record)
        headers.pop("authorization", None)
        token = (record.secrets or {}).get("token") or (record.secrets or {}).get(
            "access_token"
        )
        if token:
            headers["x-figma-token"] = str(token)
        return headers

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.figma.com if not already set."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get("base_url"):
            metadata["base_url"] = _DEFAULT_BASE_URL
        record.metadata = metadata
        return record

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
