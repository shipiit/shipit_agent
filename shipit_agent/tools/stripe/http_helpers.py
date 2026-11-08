"""Stripe REST plumbing: keys, form requests, errors and list paging."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput

from .constants import _DEFAULT_BASE_URL


class _StripeHTTP:
    """Stripe REST plumbing: keys, form requests, errors and list paging."""

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.stripe.com."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get(
            "base_url"
        ):
            metadata["base_url"] = _DEFAULT_BASE_URL
        record.metadata = metadata
        return record

    def _api_key(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("api_key")
            or secrets.get("secret_key")
            or secrets.get("token")
            or ""
        )

    def _mode(self, record: CredentialRecord) -> str:
        key = self._api_key(record)
        return "test" if key.startswith("sk_test_") else "live"

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        # Stripe uses HTTP Basic auth with the secret key as username (no password).
        # Do NOT call super()._headers() — that would produce a Bearer header.
        key = self._api_key(record)
        headers: dict[str, str] = {}
        if key:
            token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
            headers["authorization"] = f"Basic {token}"
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _request_form(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> Any:
        """POST/PATCH/DELETE with application/x-www-form-urlencoded body."""
        base_url = self._base_url(record)
        if not base_url:
            raise RuntimeError(
                f"{self.provider} credential record is missing base_url metadata."
            )
        url = f"{base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{parse.urlencode(query, doseq=True)}"
        data: bytes | None = None
        headers = self._headers(record)
        if form:
            filtered = {k: v for k, v in form.items() if v is not None}
            data = parse.urlencode(filtered, doseq=True).encode("utf-8")
            headers["content-type"] = "application/x-www-form-urlencoded"
        req = request.Request(
            url, data=data, headers=headers, method=method.upper()
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        try:
            if method.upper() == "GET":
                payload = self._request_json(
                    record=record, method=method, path=path, query=query
                )
            else:
                payload = self._request_form(
                    record=record,
                    method=method,
                    path=path,
                    query=query,
                    form=form,
                )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"Stripe request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        headers = getattr(err, "headers", None)
        if err.code == 429:
            retry_after = 0
            if headers is not None:
                try:
                    raw_retry = headers.get("Retry-After")
                    retry_after = int(raw_retry) if raw_retry is not None else 0
                except (TypeError, ValueError):
                    retry_after = 0
            return ToolOutput(
                text=(
                    "Stripe rate limit exceeded. "
                    f"Retry after {retry_after} seconds."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after": retry_after,
                    "status": 429,
                },
            )
        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"Stripe HTTP {err.code}: {message}",
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
                err_obj = parsed.get("error")
                if isinstance(err_obj, dict):
                    msg = err_obj.get("message")
                    if isinstance(msg, str) and msg:
                        return msg
                top = parsed.get("message")
                if isinstance(top, str) and top:
                    return top
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    def _base_meta(self, record: CredentialRecord, action: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "connected": True,
            "action": action,
            "mode": self._mode(record),
        }

    def _write_blocked(self, action: str, record: CredentialRecord) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Stripe write '{action}' is disabled. Construct "
                "StripeTool(allow_writes=True) to enable destructive actions."
            ),
            metadata={
                **self._base_meta(record, action),
                "error": "writes_disabled",
            },
        )

    @staticmethod
    def _require_id(
        kwargs: dict[str, Any], action: str
    ) -> tuple[str, ToolOutput | None]:
        resource_id = str(kwargs.get("id", "")).strip()
        if not resource_id:
            return "", ToolOutput(
                text=f"Stripe: `id` is required for {action}.",
                metadata={
                    "provider": "stripe",
                    "error": "missing_parameter",
                    "missing": ["id"],
                },
            )
        return resource_id, None

    def _list_query(self, kwargs: dict[str, Any], *extra_keys: str) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        if kwargs.get("starting_after"):
            query["starting_after"] = str(kwargs["starting_after"])
        for key in extra_keys:
            val = kwargs.get(key)
            if val is None or val == "":
                continue
            query[key] = val
        return query

    def _list_response(
        self,
        *,
        record: CredentialRecord,
        action: str,
        payload: Any,
        label: str,
        describe,
    ) -> ToolOutput:
        data = payload if isinstance(payload, dict) else {}
        items = data.get("data", []) or []
        lines = [describe(item) for item in items]
        text = "\n".join(lines) if lines else f"No Stripe {label} found."
        return ToolOutput(
            text=text,
            metadata={
                **self._base_meta(record, action),
                "items": items,
                "count": len(items),
                "has_more": bool(data.get("has_more")),
            },
        )
