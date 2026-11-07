"""Google Workspace API tools with reviewable edits for a local browser chat."""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

from shipit_agent.tools.base import ToolOutput

SCOPES = [
    f"https://www.googleapis.com/auth/{scope}"
    for scope in (
        "documents",
        "spreadsheets",
        "presentations",
        "drive.metadata.readonly",
    )
]
SERVICES = {
    "docs": ("https://docs.googleapis.com/v1/documents", "documentId"),
    "sheets": ("https://sheets.googleapis.com/v4/spreadsheets", "spreadsheetId"),
    "slides": ("https://slides.googleapis.com/v1/presentations", "presentationId"),
}


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


class WorkspaceTool:
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

    def _propose(self, action, service, file_id, args):
        if service not in SERVICES:
            raise ValueError("Choose docs, sheets or slides")
        if len(json.dumps(args)) > 100000:
            raise ValueError("Change proposal exceeds the size limit")
        if action == "propose_create":
            title = args.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > 250:
                raise ValueError("A title of 1–250 characters is required")
            method, url = "POST", SERVICES[service][0]
            body = (
                {"properties": {"title": title}}
                if service == "sheets"
                else {"title": title}
            )
            before = None
        elif action == "propose_values":
            if (
                service != "sheets"
                or not isinstance(args.get("range"), str)
                or not args["range"]
            ):
                raise ValueError("A Sheets range is required")
            values = args.get("values")
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(row, list) for row in values)
            ):
                raise ValueError("Provide a nonempty array of cell rows")
            before = self._read(service, file_id, args["range"])
            url = (
                self._target(service, file_id)
                + "/values/"
                + quote(args["range"], safe="")
                + "?valueInputOption=USER_ENTERED"
            )
            method, body = "PUT", {"range": args["range"], "values": values}
        else:
            requests = args.get("requests")
            if (
                not isinstance(requests, list)
                or not 1 <= len(requests) <= 100
                or any(not isinstance(r, dict) for r in requests)
            ):
                raise ValueError("Provide 1–100 Google batchUpdate request objects")
            before = self._read(service, file_id)
            method, url = "POST", self._target(service, file_id) + ":batchUpdate"
            body = {"requests": copy.deepcopy(requests)}
            if service in {"docs", "slides"}:
                revision = before.get("revisionId")
                if not revision:
                    raise ValueError(
                        "Google did not return a revision ID; cannot safely stage this edit"
                    )
                body["writeControl"] = {"requiredRevisionId": revision}
        proposal = {
            "id": uuid.uuid4().hex,
            "service": service,
            "action": action,
            "file_id": file_id,
            "method": method,
            "body": copy.deepcopy(body),
            "state": "pending",
            "range": args.get("range"),
            "concurrency": "Google revision check"
            if service in {"docs", "slides"} and action == "propose_update"
            else "Best-effort content check; Google Sheets does not provide an atomic revision guard",
        }
        with self.lock:
            if len(self.proposals) >= 20:
                raise ValueError(
                    "Review or dismiss existing proposals before preparing more"
                )
            self.proposals[proposal["id"]] = {**proposal, "url": url, "before": before}
        return {"status": "awaiting_user_apply", "proposal": proposal}

    def public_proposals(self):
        with self.lock:
            return [
                {
                    k: copy.deepcopy(v)
                    for k, v in p.items()
                    if k not in {"url", "before"}
                }
                for p in self.proposals.values()
                if p["state"] == "pending"
            ]

    def apply(self, proposal_id, approve):
        if not isinstance(proposal_id, str) or type(approve) is not bool:
            raise ValueError("A valid proposal ID and approval are required")
        with self.lock:
            proposal = self.proposals.get(proposal_id)
            if not proposal or proposal["state"] != "pending":
                raise ValueError("Proposal already resolved or missing")
            if not approve:
                del self.proposals[proposal_id]
                return {"status": "dismissed"}
            if proposal["service"] == "sheets" and proposal["before"] is not None:
                current = self._read("sheets", proposal["file_id"], proposal["range"])
                if current != proposal["before"]:
                    raise ValueError(
                        "Spreadsheet changed. Ask the agent to read it and prepare a fresh proposal."
                    )
            # Do not replay writes after ambiguous network failure.
            proposal["state"] = "submitting"
            try:
                result = self.client.request(
                    proposal["method"], proposal["url"], proposal["body"]
                )
            except Exception:
                proposal["state"] = "unknown"
                raise ValueError(
                    "Submission failed or its outcome is unknown. Check the document before proposing another change."
                ) from None
            proposal["state"] = "applied"
            return {"status": "applied", "result": result}
