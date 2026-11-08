"""Salesforce search, SOQL and record lookups."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _SalesforceReads:
    """Salesforce search, SOQL and record lookups."""

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
