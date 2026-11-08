"""The ``google_sheets`` tool: read / write Google Sheets cells, ranges, formulas, and sheet structure.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .constants import (
    _VALID_RENDER_OPTIONS,
)
from .http_helpers import _SheetsHTTP
from .prompt import GOOGLE_SHEETS_PROMPT
from .spreadsheets import _SpreadsheetActions
from .values import _ValueActions

_READ_ACTIONS = {"get_values", "batch_get", "get_metadata"}
_WRITE_ACTIONS = {
    "update_values",
    "append_values",
    "clear_values",
    "create_spreadsheet",
    "add_sheet",
}
_ACTIONS = sorted(_READ_ACTIONS | _WRITE_ACTIONS)


class GoogleSheetsTool(_SheetsHTTP, _ValueActions, _SpreadsheetActions, HTTPConnectorToolBase):
    """The ``google_sheets`` tool: read / write Google Sheets cells, ranges, formulas, and sheet structure.
    """
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

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
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
