"""Spreadsheet and sheet-tab actions."""

from __future__ import annotations

from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput


class _SpreadsheetActions:
    """Spreadsheet and sheet-tab actions."""

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
