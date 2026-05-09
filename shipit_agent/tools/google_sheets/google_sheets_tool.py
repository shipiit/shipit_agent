from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import GOOGLE_SHEETS_PROMPT


_DEFAULT_BASE_URL = "https://sheets.googleapis.com"
_DEFAULT_AUTH_SCHEME = "Bearer"
_DEFAULT_VALUE_INPUT_OPTION = "USER_ENTERED"
_VALID_RENDER_OPTIONS = {"FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"}

_READ_ACTIONS = {"get_values", "batch_get", "get_metadata"}
_WRITE_ACTIONS = {
    "update_values",
    "append_values",
    "clear_values",
    "create_spreadsheet",
    "add_sheet",
}
_ACTIONS = sorted(_READ_ACTIONS | _WRITE_ACTIONS)


class GoogleSheetsTool(HTTPConnectorToolBase):
    provider = "google_sheets"

    def __init__(
        self,
        *,
        credential_key: str = "google_sheets",
        credential_store: Any = None,
        allow_writes: bool = False,
        name: str = "google_sheets",
        description: str = (
            "Read / write Google Sheets cells, ranges, formulas, and sheet structure."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = bool(allow_writes)
        self.name = name
        self.description = description
        self.prompt = prompt or GOOGLE_SHEETS_PROMPT
        self.prompt_instructions = (
            "Use this to read cell ranges, append rows, or create/modify "
            "Google Sheets. Writes must be explicitly enabled."
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
                            "default": "get_values",
                        },
                        "spreadsheet_id": {"type": "string"},
                        "range": {"type": "string"},
                        "ranges": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "values": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {},
                            },
                            "description": (
                                "Two-dimensional list of rows; each row is a list of "
                                "cell values."
                            ),
                        },
                        "value_render_option": {
                            "type": "string",
                            "enum": sorted(_VALID_RENDER_OPTIONS),
                            "default": "FORMATTED_VALUE",
                        },
                        "title": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    # --------------------------------------------------------------- base URL

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

    # ------------------------------------------------------------- utilities

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

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        record = self._ensure_base_url(record)

        action = str(kwargs.get("action", "get_values")).strip()

        if action in _WRITE_ACTIONS and not self.allow_writes:
            return self._writes_disabled_output(action)

        handlers = {
            "get_values": self._get_values,
            "update_values": self._update_values,
            "append_values": self._append_values,
            "clear_values": self._clear_values,
            "batch_get": self._batch_get,
            "get_metadata": self._get_metadata,
            "create_spreadsheet": self._create_spreadsheet,
            "add_sheet": self._add_sheet,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Google Sheets: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ------------------------------------------------------------- actions

    def _get_values(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id", "range")
        if err is not None:
            return err
        spreadsheet_id = str(parts["spreadsheet_id"])
        range_str = str(parts["range"])
        render_option = str(
            kwargs.get("value_render_option", "FORMATTED_VALUE")
        ).strip() or "FORMATTED_VALUE"
        if render_option not in _VALID_RENDER_OPTIONS:
            return ToolOutput(
                text=(
                    "Google Sheets: unsupported value_render_option "
                    f"'{render_option}'."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_value_render_option",
                    "value_render_option": render_option,
                },
            )
        path = (
            f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/"
            f"{self._encode_range(range_str)}"
        )
        query = {"valueRenderOption": render_option}
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        values = data.get("values") or []
        text = self._values_preview_text(values)
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "range": data.get("range", range_str),
                "values": values,
                "row_count": len(values),
                "value_render_option": render_option,
            },
        )

    def _update_values(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id", "range")
        if err is not None:
            return err
        values = kwargs.get("values")
        if not isinstance(values, list) or not values:
            return ToolOutput(
                text="Google Sheets: `values` must be a non-empty 2D list for update_values.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["values"],
                },
            )
        spreadsheet_id = str(parts["spreadsheet_id"])
        range_str = str(parts["range"])
        path = (
            f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/"
            f"{self._encode_range(range_str)}"
        )
        query = {"valueInputOption": _DEFAULT_VALUE_INPUT_OPTION}
        body = {"values": values}
        payload, err = self._request_or_error(
            record=record, method="PUT", path=path, query=query, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Updated range {data.get('updatedRange', range_str)}: "
                f"{data.get('updatedCells', 0)} cells across "
                f"{data.get('updatedRows', 0)} rows."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "range": data.get("updatedRange", range_str),
                "updated_cells": data.get("updatedCells", 0),
                "updated_rows": data.get("updatedRows", 0),
                "item": data,
            },
        )

    def _append_values(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id", "range")
        if err is not None:
            return err
        values = kwargs.get("values")
        if not isinstance(values, list) or not values:
            return ToolOutput(
                text="Google Sheets: `values` must be a non-empty 2D list for append_values.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["values"],
                },
            )
        spreadsheet_id = str(parts["spreadsheet_id"])
        range_str = str(parts["range"])
        path = (
            f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/"
            f"{self._encode_range(range_str)}:append"
        )
        query = {"valueInputOption": _DEFAULT_VALUE_INPUT_OPTION}
        body = {"values": values}
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, query=query, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        updates = data.get("updates", {}) if isinstance(data, dict) else {}
        return ToolOutput(
            text=(
                f"Appended to {data.get('tableRange', range_str)}: "
                f"{updates.get('updatedCells', 0)} cells across "
                f"{updates.get('updatedRows', 0)} rows."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "range": range_str,
                "table_range": data.get("tableRange"),
                "updated_cells": updates.get("updatedCells", 0),
                "updated_rows": updates.get("updatedRows", 0),
                "item": data,
            },
        )

    def _clear_values(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id", "range")
        if err is not None:
            return err
        spreadsheet_id = str(parts["spreadsheet_id"])
        range_str = str(parts["range"])
        path = (
            f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/"
            f"{self._encode_range(range_str)}:clear"
        )
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body={}
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=f"Cleared range {data.get('clearedRange', range_str)}.",
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "range": data.get("clearedRange", range_str),
                "item": data,
            },
        )

    def _batch_get(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id")
        if err is not None:
            return err
        ranges = kwargs.get("ranges")
        if not isinstance(ranges, list) or not ranges:
            return ToolOutput(
                text="Google Sheets: `ranges` must be a non-empty list for batch_get.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["ranges"],
                },
            )
        spreadsheet_id = str(parts["spreadsheet_id"])
        path = f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values:batchGet"
        query = {"ranges": [str(r) for r in ranges]}
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        value_ranges = data.get("valueRanges", []) or []
        lines = []
        for vr in value_ranges:
            if not isinstance(vr, dict):
                continue
            lines.append(
                f"{vr.get('range', '?')}: {len(vr.get('values') or [])} rows"
            )
        text = "\n".join(lines) if lines else "No ranges returned."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "value_ranges": value_ranges,
                "count": len(value_ranges),
            },
        )

    def _get_metadata(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id")
        if err is not None:
            return err
        spreadsheet_id = str(parts["spreadsheet_id"])
        path = f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}"
        query = {"includeGridData": "false"}
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        sheets = data.get("sheets", []) or []
        sheet_info = []
        lines = []
        for sh in sheets:
            if not isinstance(sh, dict):
                continue
            props = sh.get("properties") or {}
            title = props.get("title", "?")
            sheet_id = props.get("sheetId")
            grid = props.get("gridProperties") or {}
            rows = grid.get("rowCount", "?")
            cols = grid.get("columnCount", "?")
            sheet_info.append(
                {
                    "title": title,
                    "sheet_id": sheet_id,
                    "row_count": rows,
                    "column_count": cols,
                }
            )
            lines.append(f"{title} (id={sheet_id}): {rows} rows x {cols} cols")
        spreadsheet_title = (data.get("properties") or {}).get("title", "?")
        header = f"Spreadsheet: {spreadsheet_title}"
        text = "\n".join([header] + lines) if lines else header
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "title": spreadsheet_title,
                "sheets": sheet_info,
                "count": len(sheet_info),
            },
        )

    def _create_spreadsheet(self, *, record, action, kwargs):
        title = str(kwargs.get("title", "")).strip()
        if not title:
            return ToolOutput(
                text="Google Sheets: `title` is required for create_spreadsheet.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["title"],
                },
            )
        path = "/v4/spreadsheets"
        body = {"properties": {"title": title}}
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Created spreadsheet `{title}` "
                f"(id={data.get('spreadsheetId', '?')})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "title": title,
                "spreadsheet_id": data.get("spreadsheetId"),
                "spreadsheet_url": data.get("spreadsheetUrl"),
                "item": data,
            },
        )

    def _add_sheet(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "spreadsheet_id", "title")
        if err is not None:
            return err
        spreadsheet_id = str(parts["spreadsheet_id"])
        title = str(parts["title"])
        path = f"/v4/spreadsheets/{quote(spreadsheet_id, safe='')}:batchUpdate"
        body = {
            "requests": [
                {"addSheet": {"properties": {"title": title}}},
            ],
        }
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        replies = data.get("replies", []) or []
        sheet_id = None
        if replies and isinstance(replies[0], dict):
            added = replies[0].get("addSheet", {})
            sheet_id = (added.get("properties") or {}).get("sheetId")
        return ToolOutput(
            text=(
                f"Added sheet `{title}` "
                f"(id={sheet_id if sheet_id is not None else '?'})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "spreadsheet_id": spreadsheet_id,
                "title": title,
                "sheet_id": sheet_id,
                "item": data,
            },
        )

    # ---------------------------------------------------------- text helpers

    @staticmethod
    def _values_preview_text(values: list) -> str:
        if not values:
            return "No values in range."
        preview = values[:10]
        # Markdown table; use the widest row as the column count.
        width = max((len(row) for row in preview), default=0)
        if width == 0:
            return f"Range has {len(values)} rows (all empty)."

        def _cell(cell: Any) -> str:
            text = "" if cell is None else str(cell)
            # Keep the table parser happy.
            return text.replace("|", "\\|").replace("\n", " ")

        def _row(row: list) -> str:
            cells = [_cell(c) for c in row]
            while len(cells) < width:
                cells.append("")
            return "| " + " | ".join(cells) + " |"

        header = _row(preview[0])
        divider = "| " + " | ".join(["---"] * width) + " |"
        rows = [_row(r) for r in preview[1:]]
        total = len(values)
        footer = (
            f"\n(Showing {len(preview)} of {total} rows.)"
            if total > len(preview)
            else ""
        )
        return "\n".join([header, divider, *rows]) + footer
