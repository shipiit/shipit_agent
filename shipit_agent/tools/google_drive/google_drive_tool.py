from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import ConnectorToolBase
from .prompt import GOOGLE_DRIVE_PROMPT


class GoogleDriveTool(ConnectorToolBase):
    provider = "google_drive"

    def __init__(self, *, credential_key: str = "google_drive", credential_store=None, name: str = "google_drive", description: str = "Search and list Google Drive files.", prompt: str | None = None) -> None:
        super().__init__(credential_key=credential_key, credential_store=credential_store)
        self.name = name
        self.description = description
        self.prompt = prompt or GOOGLE_DRIVE_PROMPT
        self.prompt_instructions = "Use this for document discovery and Drive file lookup."

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["search_files"], "default": "search_files"}, "query": {"type": "string"}, "page_size": {"type": "integer", "default": 10}}, "required": ["action"]}}}

    def _build_service(self, record):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Install `google-api-python-client` and `google-auth` to use GoogleDriveTool.") from exc
        from google.oauth2.credentials import Credentials
        tokens = record.secrets.get("google_tokens", record.secrets)
        creds = Credentials(token=tokens.get("access_token"), refresh_token=tokens.get("refresh_token"), token_uri="https://oauth2.googleapis.com/token", client_id=tokens.get("client_id"), client_secret=tokens.get("client_secret"))
        return build("drive", "v3", credentials=creds)

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        service = self._build_service(record)
        response = service.files().list(q=str(kwargs.get("query", "")).strip() or None, pageSize=int(kwargs.get("page_size", 10)), fields="files(id,name,mimeType,webViewLink)").execute()
        items = response.get("files", [])
        lines = [f"{item.get('name', '?')} | {item.get('mimeType', '?')} | {item.get('webViewLink', '')}" for item in items]
        return ToolOutput(text="\n".join(lines) if lines else "No Google Drive files found.", metadata={"provider": self.provider, "connected": True, "items": items, "count": len(items)})
