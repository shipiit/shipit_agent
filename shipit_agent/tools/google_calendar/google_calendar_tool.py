from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import ConnectorToolBase
from .prompt import GOOGLE_CALENDAR_PROMPT


class GoogleCalendarTool(ConnectorToolBase):
    provider = "google_calendar"

    def __init__(self, *, credential_key: str = "google_calendar", credential_store=None, name: str = "google_calendar", description: str = "Search and list Google Calendar events.", prompt: str | None = None) -> None:
        super().__init__(credential_key=credential_key, credential_store=credential_store)
        self.name = name
        self.description = description
        self.prompt = prompt or GOOGLE_CALENDAR_PROMPT
        self.prompt_instructions = "Use this for calendar scheduling context, upcoming events, and event search."

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list_events"], "default": "list_events"}, "calendar_id": {"type": "string", "default": "primary"}, "query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}}, "required": ["action"]}}}

    def _build_service(self, record):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Install `google-api-python-client` and `google-auth` to use GoogleCalendarTool.") from exc
        from google.oauth2.credentials import Credentials
        tokens = record.secrets.get("google_tokens", record.secrets)
        creds = Credentials(token=tokens.get("access_token"), refresh_token=tokens.get("refresh_token"), token_uri="https://oauth2.googleapis.com/token", client_id=tokens.get("client_id"), client_secret=tokens.get("client_secret"))
        return build("calendar", "v3", credentials=creds)

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        service = self._build_service(record)
        action = str(kwargs.get("action", "list_events"))
        if action != "list_events":
            raise ValueError(f"Unsupported Google Calendar action: {action}")
        response = service.events().list(calendarId=str(kwargs.get("calendar_id", "primary")), q=str(kwargs.get("query", "")).strip() or None, maxResults=int(kwargs.get("max_results", 10)), singleEvents=True, orderBy="startTime").execute()
        items = response.get("items", [])
        lines = [f"{item.get('summary', '(No Title)')} | {item.get('start', {}).get('dateTime') or item.get('start', {}).get('date')} | {item.get('htmlLink', '')}" for item in items]
        return ToolOutput(text="\n".join(lines) if lines else "No Google Calendar events found.", metadata={"provider": self.provider, "connected": True, "action": action, "items": items, "count": len(items)})
