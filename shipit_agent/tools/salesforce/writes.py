"""Salesforce record changes."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _SalesforceWrites:
    """Salesforce record changes."""

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
