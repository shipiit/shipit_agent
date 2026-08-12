from __future__ import annotations

import json
from typing import Any
from urllib import parse, request

from shipit_agent.integrations import CredentialRecord, CredentialStore
from shipit_agent.tools.base import ToolContext, ToolOutput


class ConnectorToolBase:
    provider: str = "connector"

    def __init__(
        self, *, credential_key: str, credential_store: CredentialStore | None = None
    ) -> None:
        self.credential_key = credential_key
        self.credential_store = credential_store

    def _resolve_store(self, context: ToolContext) -> CredentialStore | None:
        shared = context.state.get("credential_store")
        if shared is not None:
            return shared
        return self.credential_store

    def _get_record(self, context: ToolContext) -> CredentialRecord | None:
        store = self._resolve_store(context)
        if store is None:
            return None
        return store.get(self.credential_key)

    def _not_connected_output(self, context: ToolContext | None = None) -> ToolOutput:
        """A missing credential produces an ACTIONABLE result, not a dead end.

        With the run's ConnectionRegistry in reach (published into shared
        state by the runtime), this files a connection request and returns
        the ``requested`` metadata that makes the runtime emit its
        ``connection_requested`` card — the user sees "Connect Slack — it
        needs a token", the model sees the same instruction, and neither is
        left guessing. Without a registry (bare tool, unit test) it degrades
        to the old flat text.
        """
        registry = None
        if context is not None:
            registry = (getattr(context, "state", None) or {}).get(
                "connection_registry"
            )
        base_metadata = {
            "provider": self.provider,
            "connected": False,
            "credential_key": self.credential_key,
        }
        if registry is None:
            return ToolOutput(
                text=(
                    f"{self.provider} is not connected. Configure a "
                    "credential record first."
                ),
                metadata=base_metadata,
            )
        reason = f"The {self.provider} tool was called but has no credential."
        try:
            registry.request(self.credential_key, reason)
            connection = registry.get(self.credential_key)
        except Exception:
            connection = None
        next_step = connection.next_step() if connection is not None else ""
        title = getattr(connection, "title", None) or self.provider
        auth = getattr(getattr(connection, "auth", None), "value", "unknown")
        return ToolOutput(
            text=(
                f"{self.provider} is not connected. {next_step or 'A credential is required.'} "
                "The request has been filed; tell the user what is needed and "
                "continue with what you can do without it."
            ),
            metadata={
                **base_metadata,
                "requested": True,
                "connection_id": self.credential_key,
                "title": title,
                "reason": reason,
                "auth": auth,
            },
        )


class HTTPConnectorToolBase(ConnectorToolBase):
    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        token = (
            record.secrets.get("api_key")
            or record.secrets.get("token")
            or record.secrets.get("access_token")
        )
        if token:
            auth_scheme = str(record.metadata.get("auth_scheme", "Bearer"))
            headers["authorization"] = f"{auth_scheme} {token}"
        extra = record.metadata.get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(key): str(value) for key, value in extra.items()})
        return headers

    def _base_url(self, record: CredentialRecord) -> str:
        return str(
            record.metadata.get("base_url") or record.secrets.get("base_url") or ""
        ).rstrip("/")

    def _request_json(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        base_url = self._base_url(record)
        if not base_url:
            raise RuntimeError(
                f"{self.provider} credential record is missing base_url metadata."
            )
        url = f"{base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{parse.urlencode(query, doseq=True)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(
            url, data=data, headers=self._headers(record), method=method.upper()
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}
