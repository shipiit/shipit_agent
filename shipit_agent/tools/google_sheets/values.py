"""Sheets cell-value actions."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput

from .constants import (
    _DEFAULT_VALUE_INPUT_OPTION,
    _VALID_RENDER_OPTIONS,
)


class _ValueActions:
    """Sheets cell-value actions."""

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
