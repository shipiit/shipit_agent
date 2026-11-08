"""Salesforce REST plumbing: paths, requests, errors and record rendering."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput


class _SalesforceHTTP:
    """Salesforce REST plumbing: paths, requests, errors and record rendering."""

    def _api_path(self, suffix: str) -> str:
        suffix = suffix.lstrip("/")
        return f"/services/data/{self.api_version}/{suffix}"

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        try:
            payload = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"Salesforce request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        code = int(getattr(err, "code", 0) or 0)
        if code == 401:
            return ToolOutput(
                text="Salesforce token expired — refresh and retry.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "auth_expired",
                    "status": 401,
                },
            )
        if code == 429:
            retry_after_seconds = 0
            headers = getattr(err, "headers", None)
            if headers is not None:
                try:
                    raw = headers.get("Retry-After")
                    if raw is not None:
                        retry_after_seconds = int(str(raw).strip())
                except (TypeError, ValueError):
                    retry_after_seconds = 0
            return ToolOutput(
                text=(
                    "Salesforce rate limit exceeded. Retry after "
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
            text=f"Salesforce HTTP {code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": code,
                "message": message,
            },
        )

    @staticmethod
    def _extract_error_message(err: HTTPError) -> str:
        try:
            raw = err.read()
            if raw:
                decoded = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(decoded)
                except json.JSONDecodeError:
                    return decoded[:300] or "unknown_error"
                # Salesforce error bodies are typically [{"message": "...", "errorCode": "..."}]
                if isinstance(parsed, list) and parsed:
                    first = parsed[0]
                    if isinstance(first, dict):
                        msg = first.get("message") or first.get("errorCode")
                        if isinstance(msg, str) and msg:
                            return msg
                if isinstance(parsed, dict):
                    msg = parsed.get("message") or parsed.get("error_description")
                    if isinstance(msg, str) and msg:
                        return msg
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    def _writes_disabled_output(self, action: str) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Salesforce writes are disabled for this tool instance "
                f"(action '{action}')."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "writes_disabled",
                "action": action,
                "hint": (
                    "Construct SalesforceTool(allow_writes=True) to enable mutations."
                ),
            },
        )

    @staticmethod
    def _render_records(records: list[dict[str, Any]], limit: int = 10) -> str:
        if not records:
            return "(no records)"
        subset = records[:limit]
        # Collect a stable column order from the first record (excluding attributes).
        columns: list[str] = []
        for rec in subset:
            if not isinstance(rec, dict):
                continue
            for key in rec.keys():
                if key == "attributes":
                    continue
                if key not in columns:
                    columns.append(key)
        if not columns:
            return "(no columns)"
        header = " | ".join(columns)
        separator = " | ".join("---" for _ in columns)
        rows: list[str] = [header, separator]
        for rec in subset:
            if not isinstance(rec, dict):
                continue
            rows.append(
                " | ".join(str(rec.get(col, "")) for col in columns)
            )
        return "\n".join(rows)
