"""Sheets REST plumbing: requests, error output, quota and range helpers."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput

from .constants import (
    _DEFAULT_AUTH_SCHEME,
    _DEFAULT_BASE_URL,
)


class _SheetsHTTP:
    """Sheets REST plumbing: requests, error output, quota and range helpers."""

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to sheets.googleapis.com and auth_scheme to Bearer."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get("base_url"):
            metadata["base_url"] = _DEFAULT_BASE_URL
        if not metadata.get("auth_scheme"):
            metadata["auth_scheme"] = _DEFAULT_AUTH_SCHEME
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
        """Call _request_json; return (payload, None) on success, (None, error) on failure."""
        try:
            payload = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"Google Sheets request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        parsed = self._parse_error_body(err)
        message = self._extract_error_message(parsed) or "unknown_error"

        if err.code == 429:
            retry_after_seconds = self._retry_after_seconds(err)
            return ToolOutput(
                text=(
                    "Google Sheets rate limit exceeded. Retry after "
                    f"{retry_after_seconds} seconds."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "status": 429,
                    "retry_after_seconds": retry_after_seconds,
                    "message": message,
                },
            )

        if err.code == 403:
            quota_metric, quota_reason = self._extract_quota_info(parsed)
            if quota_reason == "rateLimitExceeded" or quota_metric:
                return ToolOutput(
                    text=(
                        "Google Sheets quota exceeded"
                        + (f" for `{quota_metric}`" if quota_metric else "")
                        + "."
                    ),
                    metadata={
                        "provider": self.provider,
                        "connected": True,
                        "error": "quota_exceeded",
                        "status": 403,
                        "quota_metric": quota_metric,
                        "quota_reason": quota_reason,
                        "message": message,
                    },
                )

        return ToolOutput(
            text=f"Google Sheets HTTP {err.code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": int(err.code),
                "message": message,
            },
        )

    @staticmethod
    def _parse_error_body(err: HTTPError) -> dict[str, Any]:
        try:
            raw = err.read()
            if raw:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        return {}

    @staticmethod
    def _extract_error_message(parsed: dict[str, Any]) -> str | None:
        error_obj = parsed.get("error")
        if isinstance(error_obj, dict):
            msg = error_obj.get("message")
            if isinstance(msg, str) and msg:
                return msg
        msg = parsed.get("message")
        if isinstance(msg, str) and msg:
            return msg
        return None

    @staticmethod
    def _extract_quota_info(parsed: dict[str, Any]) -> tuple[str | None, str | None]:
        error_obj = parsed.get("error")
        if not isinstance(error_obj, dict):
            return None, None
        metric: str | None = None
        reason: str | None = None
        details = error_obj.get("details")
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                if item.get("reason") and reason is None:
                    reason = str(item.get("reason"))
                if item.get("@type", "").endswith("QuotaFailure"):
                    violations = item.get("violations")
                    if isinstance(violations, list):
                        for v in violations:
                            if isinstance(v, dict) and v.get("quotaMetric"):
                                metric = str(v.get("quotaMetric"))
                                break
        errors_list = error_obj.get("errors")
        if reason is None and isinstance(errors_list, list):
            for item in errors_list:
                if isinstance(item, dict) and item.get("reason"):
                    reason = str(item.get("reason"))
                    break
        return metric, reason

    @staticmethod
    def _retry_after_seconds(err: HTTPError) -> int:
        headers = getattr(err, "headers", None)
        if headers is None:
            return 0
        try:
            value = headers.get("Retry-After")
        except Exception:  # pragma: no cover - defensive
            return 0
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _encode_range(range_str: str) -> str:
        return quote(range_str, safe="")

    @staticmethod
    def _require(kwargs: dict[str, Any], *names: str) -> tuple[dict[str, Any], ToolOutput | None]:
        missing = [n for n in names if not str(kwargs.get(n, "")).strip()]
        if missing:
            return {}, ToolOutput(
                text=f"Google Sheets: missing required parameter(s) {', '.join(missing)}.",
                metadata={
                    "provider": "google_sheets",
                    "error": "missing_parameter",
                    "missing": missing,
                },
            )
        return {n: kwargs.get(n) for n in names}, None

    def _writes_disabled_output(self, action: str) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Google Sheets: writes are disabled for this tool, cannot run "
                f"`{action}`. Enable writes with GoogleSheetsTool(allow_writes=True)."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "writes_disabled",
                "action": action,
            },
        )
