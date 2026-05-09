from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import SALESFORCE_PROMPT


_ACTIONS = [
    "search",
    "query",
    "get_record",
    "list_accounts",
    "list_opportunities",
    "list_contacts",
    "create_record",
    "update_record",
    "log_activity",
]


class SalesforceTool(HTTPConnectorToolBase):
    provider = "salesforce"

    def __init__(
        self,
        *,
        credential_key: str = "salesforce",
        credential_store: Any = None,
        allow_writes: bool = False,
        api_version: str = "v60.0",
        name: str = "salesforce",
        description: str = (
            "Search Salesforce records; query SOQL/SOSL; read accounts/opportunities/"
            "contacts; log activities."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = bool(allow_writes)
        self.api_version = api_version.strip() or "v60.0"
        self.name = name
        self.description = description
        self.prompt = prompt or SALESFORCE_PROMPT
        self.prompt_instructions = (
            "Use this for Salesforce CRM lookups (accounts, opportunities, contacts), "
            "SOQL/SOSL queries, and activity logging. Writes are gated behind "
            "allow_writes; log_activity is always allowed."
        )

    # ------------------------------------------------------------------ schema

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": list(_ACTIONS),
                            "default": "query",
                        },
                        "query": {
                            "type": "string",
                            "description": "SOSL query string for the search action.",
                        },
                        "soql": {
                            "type": "string",
                            "description": "SOQL query string for the query action.",
                        },
                        "sobject": {
                            "type": "string",
                            "description": "Salesforce object API name (Account, Contact, ...).",
                        },
                        "record_id": {"type": "string"},
                        "fields": {
                            "type": "object",
                            "description": "Field name → value map for create/update.",
                        },
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "related_to_id": {
                            "type": "string",
                            "description": (
                                "Id of the Account / Opportunity / other record the "
                                "activity relates to (mapped to Task.WhatId)."
                            ),
                        },
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["action"],
                },
            },
        }

    # -------------------------------------------------------------- path helper

    def _api_path(self, suffix: str) -> str:
        suffix = suffix.lstrip("/")
        return f"/services/data/{self.api_version}/{suffix}"

    # ---------------------------------------------------------- HTTP wrapper

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

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()

        if not self._base_url(record):
            return ToolOutput(
                text=(
                    "Salesforce credential record is missing the instance URL "
                    "(base_url)."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "missing_instance_url",
                    "hint": (
                        "Set base_url on the Salesforce CredentialRecord to your "
                        "org's instance URL, e.g. https://acme.my.salesforce.com"
                    ),
                },
            )

        action = str(kwargs.get("action", "")).strip()

        handlers = {
            "search": self._search,
            "query": self._query,
            "get_record": self._get_record_action,
            "list_accounts": self._list_accounts,
            "list_opportunities": self._list_opportunities,
            "list_contacts": self._list_contacts,
            "create_record": self._create_record,
            "update_record": self._update_record,
            "log_activity": self._log_activity,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Salesforce: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ---------------------------------------------------------- write guard

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

    # ------------------------------------------------------------- rendering

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

    # ----------------------------------------------------------- read actions

    def _search(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="Salesforce: `query` (SOSL) is required for search.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        path = self._api_path("search")
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query={"q": q}
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        records = data.get("searchRecords") or []
        if not isinstance(records, list):
            records = []
        total = len(records)
        text = (
            f"totalSize: {total}\n" + self._render_records(records, limit=10)
            if records
            else f"totalSize: {total}\nNo Salesforce records matched the query."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "records": records,
                "totalSize": total,
            },
        )

    def _query(self, *, record, action, kwargs):
        soql = str(kwargs.get("soql", "")).strip()
        if not soql:
            return ToolOutput(
                text="Salesforce: `soql` is required for query.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        return self._run_query(record=record, action=action, soql=soql)

    def _run_query(self, *, record, action, soql: str) -> ToolOutput:
        path = self._api_path("query")
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query={"q": soql}
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        records = data.get("records") or []
        if not isinstance(records, list):
            records = []
        total = data.get("totalSize", len(records))
        text = (
            f"totalSize: {total}\n" + self._render_records(records, limit=10)
            if records
            else f"totalSize: {total}\nNo Salesforce records matched the query."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "soql": soql,
                "records": records,
                "totalSize": total,
                "done": data.get("done"),
                "nextRecordsUrl": data.get("nextRecordsUrl"),
            },
        )

    def _get_record_action(self, *, record, action, kwargs):
        sobject = str(kwargs.get("sobject", "")).strip()
        record_id = str(kwargs.get("record_id", "")).strip()
        missing = [
            name
            for name, value in (("sobject", sobject), ("record_id", record_id))
            if not value
        ]
        if missing:
            return ToolOutput(
                text=(
                    "Salesforce: missing required parameter(s) "
                    f"{', '.join(missing)} for get_record."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": missing,
                    "action": action,
                },
            )
        path = self._api_path(f"sobjects/{sobject}/{record_id}")
        payload, err = self._request_or_error(
            record=record, method="GET", path=path
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        label = data.get("Name") or data.get("Subject") or record_id
        text = f"{sobject} {record_id}: {label}"
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "sobject": sobject,
                "record_id": record_id,
                "item": data,
            },
        )

    def _resolve_limit(self, kwargs: dict[str, Any], default: int = 50) -> int:
        raw = kwargs.get("limit")
        try:
            value = int(raw) if raw is not None else default
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, 2000))

    def _list_accounts(self, *, record, action, kwargs):
        limit = self._resolve_limit(kwargs)
        soql = (
            f"SELECT Id, Name, Industry, Website, AnnualRevenue FROM Account "
            f"LIMIT {limit}"
        )
        return self._run_query(record=record, action=action, soql=soql)

    def _list_opportunities(self, *, record, action, kwargs):
        limit = self._resolve_limit(kwargs)
        soql = (
            f"SELECT Id, Name, StageName, Amount, CloseDate, AccountId FROM "
            f"Opportunity WHERE IsClosed = false LIMIT {limit}"
        )
        return self._run_query(record=record, action=action, soql=soql)

    def _list_contacts(self, *, record, action, kwargs):
        limit = self._resolve_limit(kwargs)
        soql = (
            f"SELECT Id, FirstName, LastName, Email, Title, AccountId FROM "
            f"Contact LIMIT {limit}"
        )
        return self._run_query(record=record, action=action, soql=soql)

    # ---------------------------------------------------------- write actions

    def _create_record(self, *, record, action, kwargs):
        if not self.allow_writes:
            return self._writes_disabled_output(action)
        sobject = str(kwargs.get("sobject", "")).strip()
        fields = kwargs.get("fields")
        if not sobject:
            return ToolOutput(
                text="Salesforce: `sobject` is required for create_record.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        if not isinstance(fields, dict) or not fields:
            return ToolOutput(
                text="Salesforce: `fields` object is required for create_record.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        path = self._api_path(f"sobjects/{sobject}")
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=dict(fields)
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        new_id = data.get("id") or data.get("Id")
        return ToolOutput(
            text=f"Created {sobject} {new_id or '(unknown id)'}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "sobject": sobject,
                "id": new_id,
                "item": data,
            },
        )

    def _update_record(self, *, record, action, kwargs):
        if not self.allow_writes:
            return self._writes_disabled_output(action)
        sobject = str(kwargs.get("sobject", "")).strip()
        record_id = str(kwargs.get("record_id", "")).strip()
        fields = kwargs.get("fields")
        missing = [
            name
            for name, value in (("sobject", sobject), ("record_id", record_id))
            if not value
        ]
        if missing:
            return ToolOutput(
                text=(
                    "Salesforce: missing required parameter(s) "
                    f"{', '.join(missing)} for update_record."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": missing,
                    "action": action,
                },
            )
        if not isinstance(fields, dict) or not fields:
            return ToolOutput(
                text="Salesforce: `fields` object is required for update_record.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        path = self._api_path(f"sobjects/{sobject}/{record_id}")
        _payload, err = self._request_or_error(
            record=record, method="PATCH", path=path, body=dict(fields)
        )
        if err is not None:
            return err
        return ToolOutput(
            text=f"Updated {sobject} {record_id}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "sobject": sobject,
                "record_id": record_id,
                "updated_fields": sorted(fields.keys()),
            },
        )

    def _log_activity(self, *, record, action, kwargs):
        subject = str(kwargs.get("subject", "")).strip()
        description = kwargs.get("description")
        related_to_id = str(kwargs.get("related_to_id", "")).strip()
        if not subject:
            return ToolOutput(
                text="Salesforce: `subject` is required for log_activity.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "action": action,
                },
            )
        body: dict[str, Any] = {"Subject": subject}
        if description is not None:
            body["Description"] = str(description)
        if related_to_id:
            body["WhatId"] = related_to_id
        path = self._api_path("sobjects/Task")
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        task_id = data.get("id") or data.get("Id")
        suffix = f" (related to {related_to_id})" if related_to_id else ""
        return ToolOutput(
            text=f"Logged activity '{subject}'{suffix} as Task {task_id or '(unknown id)'}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "id": task_id,
                "related_to_id": related_to_id or None,
                "item": data,
            },
        )
