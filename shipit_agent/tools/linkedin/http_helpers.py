"""LinkedIn provider plumbing: auth, requests and error output."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput

from .constants import _DEFAULT_API_KEY_QUERY_PARAM


class _LinkedInHTTP:
    """LinkedIn provider plumbing: auth, requests and error output."""

    def _auth_mode(self, record: CredentialRecord) -> str:
        mode = str((record.metadata or {}).get("auth_mode", "bearer")).strip().lower()
        if mode not in {"bearer", "api_key_header", "query_param"}:
            return "bearer"
        return mode

    def _token(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("token")
            or secrets.get("api_key")
            or secrets.get("access_token")
            or ""
        )

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        mode = self._auth_mode(record)
        token = self._token(record)

        if mode == "bearer":
            headers = {"content-type": "application/json"}
            if token:
                headers["authorization"] = f"Bearer {token}"
            extra = (record.metadata or {}).get("headers", {})
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
            return headers

        if mode == "api_key_header":
            headers = {"content-type": "application/json"}
            header_name = str(
                (record.metadata or {}).get("api_key_header", "X-API-Key")
            )
            if token:
                headers[header_name] = token
            extra = (record.metadata or {}).get("headers", {})
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
            return headers

        # query_param mode — no auth header at all; token rides on the URL.
        headers = {"content-type": "application/json"}
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _augment_query(
        self, record: CredentialRecord, query: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if self._auth_mode(record) != "query_param":
            return query
        param_name = str(
            (record.metadata or {}).get(
                "api_key_query_param", _DEFAULT_API_KEY_QUERY_PARAM
            )
        )
        token = self._token(record)
        merged: dict[str, Any] = dict(query or {})
        if token:
            merged[param_name] = token
        return merged

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
                record=record,
                method=method,
                path=path,
                query=self._augment_query(record, query),
                body=body,
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"LinkedIn request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        code = int(getattr(err, "code", 0) or 0)
        headers = getattr(err, "headers", None)
        retry_after: int | None = None
        if headers is not None:
            try:
                raw = headers.get("Retry-After")
                if raw is not None:
                    retry_after = int(raw)
            except (TypeError, ValueError):
                retry_after = None
        if code == 429:
            return ToolOutput(
                text=(
                    "LinkedIn rate limit exceeded."
                    + (f" Retry after {retry_after}s." if retry_after else "")
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "status": 429,
                    "retry_after": retry_after,
                },
            )

        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"LinkedIn HTTP {code}: {message}",
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
                    msg = (
                        parsed.get("message")
                        or parsed.get("error")
                        or parsed.get("detail")
                    )
                    if isinstance(msg, str) and msg:
                        return msg
                except json.JSONDecodeError:
                    if decoded:
                        return decoded[:300]
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    def _missing_base_url_output(self) -> ToolOutput:
        return ToolOutput(
            text=(
                "LinkedIn: missing base_url on the credential record. Point it at an "
                "API vendor such as Proxycurl (https://nubela.co/proxycurl/api) or a "
                "RapidAPI LinkedIn endpoint, and set `metadata.base_url` accordingly."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "missing_base_url",
                "hint": (
                    "Configure metadata.base_url — e.g. Proxycurl "
                    "'https://nubela.co/proxycurl/api' or a RapidAPI endpoint — "
                    "and set metadata.auth_mode (bearer | api_key_header | query_param)."
                ),
            },
        )
