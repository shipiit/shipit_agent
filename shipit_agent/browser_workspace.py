"""Google Workspace API tools with reviewable edits for a local browser chat."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput

from .browser_proposals import _ProposalActions
from .browser_workspace_services import SERVICES

SCOPES = [
    f"https://www.googleapis.com/auth/{scope}"
    for scope in (
        "documents",
        "spreadsheets",
        "presentations",
        "drive.metadata.readonly",
    )
]


class GoogleWorkspaceClient:
    def __init__(self, token_file: str):
        self.token_file = Path(token_file).expanduser()
        self.lock = threading.Lock()
        self._session = None

    @property
    def connected(self):
        return self.token_file.is_file()

    def request(self, method, url, body=None):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.credentials import Credentials

        # All URLs are constructed by WorkspaceTool, never supplied by the model.
        with self.lock:
            if not self._session:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_file), scopes=SCOPES
                )
                self._session = AuthorizedSession(creds)
            response = self._session.request(
                method, url, json=body, timeout=30, allow_redirects=False
            )
        if not response.ok:
            raise ValueError(
                f"Google Workspace returned HTTP {response.status_code}; check account access and API scopes"
            )
        if len(response.content) > 4 * 1024 * 1024:
            raise ValueError(
                "Workspace response exceeded 4 MB; request a smaller document or range"
            )
        return response.json()


def google_login(client_file: str, token_file: str):
    """Run only from the user's terminal; tokens never enter the model or sidebar."""
    import os

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    credentials = flow.run_local_server(port=0)
    path = Path(token_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(credentials.to_json())


class WorkspaceTool(_ProposalActions):
    name = "google_workspace"
    description = "Read Google Docs, Sheets or Slides; search Drive; prepare document changes for the user's Apply button."
    prompt_instructions = (
        "Use actual Workspace APIs for document contents, especially canvas editors. "
        "Use read before proposing updates. A proposed update has NOT been applied. "
        "Changes require the user's Apply button. For Docs/Slides, use exact object/index "
        "information returned by read; never guess IDs. Google Sheets is the Workspace "
        "spreadsheet app; uploaded Excel/PowerPoint files are separate attachments."
    )

    def __init__(self, client):
        self.client = client
        self.proposals = {}
        self.lock = threading.Lock()

    def schema(self):
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
                            "enum": [
                                "search",
                                "read",
                                "propose_create",
                                "propose_update",
                                "propose_values",
                            ],
                        },
                        "service": {"type": "string", "enum": list(SERVICES)},
                        "file_id": {"type": "string"},
                        "query": {
                            "type": "string",
                            "description": "Drive search query, e.g. name contains 'Quarterly'",
                        },
                        "range": {
                            "type": "string",
                            "description": "Sheets A1 range, e.g. Sheet1!A1:D20",
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "array", "items": {}},
                        },
                        "title": {"type": "string"},
                        "requests": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Google API batchUpdate requests for the selected service; exact changes shown for review",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        }

    @staticmethod
    def _target(service, file_id):
        if (
            service not in SERVICES
            or not isinstance(file_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", file_id)
        ):
            raise ValueError("Choose docs, sheets or slides and a valid file ID")
        return SERVICES[service][0] + "/" + quote(file_id, safe="")

    def _read(self, service, file_id, range=None):
        url = self._target(service, file_id)
        if service == "sheets" and range:
            url += "/values/" + quote(range, safe="") + "?valueRenderOption=FORMULA"
        elif service == "docs":
            url += "?includeTabsContent=true"
        return self.client.request("GET", url)

    def run(self, context, **args):
        try:
            if not self.client.connected:
                raise ValueError(
                    "Google Workspace is not connected. Run the local Google login command first."
                )
            action, service, file_id = (
                args.get("action"),
                args.get("service"),
                args.get("file_id"),
            )
            if action == "search":
                query = args.get("query", "trashed = false")
                if not isinstance(query, str) or len(query) > 2000:
                    raise ValueError("Invalid Drive search query")
                url = (
                    "https://www.googleapis.com/drive/v3/files?pageSize=20&fields="
                    + quote(
                        "files(id,name,mimeType,webViewLink),nextPageToken", safe=""
                    )
                    + "&q="
                    + quote(query, safe="")
                )
                payload = self.client.request("GET", url)
            elif action == "read":
                payload = self._read(service, file_id, args.get("range"))
            elif action in {"propose_create", "propose_update", "propose_values"}:
                payload = self._propose(action, service, file_id, args)
            else:
                raise ValueError("Unknown Workspace action")
            text = json.dumps(payload, ensure_ascii=False)
            model_text = (
                text
                if len(text) <= 30000
                else text[:30000]
                + "\n[Response truncated; narrow the requested range or document.]"
            )
            return ToolOutput(
                text=text,
                model_text=model_text,
                metadata={"ok": True, "provider": "google_workspace"},
            )
        except (ValueError, OSError, ImportError) as exc:
            return ToolOutput(text=str(exc), metadata={"ok": False, "error": str(exc)})
