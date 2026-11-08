"""Zendesk REST plumbing: credentials, requests and error output."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput


class _ZendeskHTTP:
    """Zendesk REST plumbing: credentials, requests and error output."""

    def _credential_email(self, record: CredentialRecord) -> str:
        return str(
            (record.secrets or {}).get("email")
            or (record.metadata or {}).get("email")
            or ""
        ).strip()

    def _credential_token(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("api_token")
            or secrets.get("token")
            or ""
        ).strip()

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json"}
        email = self._credential_email(record)
        token = self._credential_token(record)
        if email and token:
            raw = f"{email}/token:{token}".encode("utf-8")
            encoded = base64.b64encode(raw).decode("ascii")
            headers["authorization"] = f"Basic {encoded}"
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _missing_subdomain_output(self) -> ToolOutput:
        return ToolOutput(
            text=(
                "Zendesk: missing subdomain. Set `metadata.base_url = "
                "https://{subdomain}.zendesk.com` on the credential record."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "missing_subdomain",
                "hint": "metadata.base_url = https://{subdomain}.zendesk.com",
            },
        )

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
                text=f"Zendesk request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        if err.code == 429:
            retry_after_seconds = 0
            headers = getattr(err, "headers", None)
            if headers is not None:
                try:
                    raw = headers.get("Retry-After")
                    if raw is not None:
                        retry_after_seconds = int(raw)
                except (TypeError, ValueError):
                    retry_after_seconds = 0
            return ToolOutput(
                text=(
                    "Zendesk rate limit exceeded. Retry after "
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
            text=f"Zendesk HTTP {err.code}: {message}",
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
                description = parsed.get("description")
                if isinstance(description, str) and description:
                    return description
                error_name = parsed.get("error")
                if isinstance(error_name, str) and error_name:
                    return error_name
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    def _writes_disabled_output(self, action: str) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Zendesk: action '{action}' requires allow_writes=True. "
                "Construct ZendeskTool(allow_writes=True) to enable writes."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "writes_disabled",
                "action": action,
            },
        )

    @staticmethod
    def _ticket_line(ticket: dict[str, Any]) -> str:
        tid = ticket.get("id", "?")
        status = ticket.get("status", "?")
        subject = ticket.get("subject", "")
        url = ticket.get("url", "")
        return f"#{tid} [{status}] {subject}  {url}".rstrip()
