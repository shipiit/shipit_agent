"""The ``gmail_search`` tool: search, read, draft, and send Gmail messages from a configured Google account.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.integrations import CredentialStore
from shipit_agent.tools.base import ToolContext, ToolOutput

from .actions import _GmailActions
from .messages import _MessageFormatting
from .prompt import GMAIL_PROMPT


class GmailTool(_MessageFormatting, _GmailActions):
    """The ``gmail_search`` tool: search, read, draft, and send Gmail messages from a configured Google account.
    """
    def __init__(
        self,
        *,
        credential_key: str = "gmail",
        credential_store: CredentialStore | None = None,
        name: str = "gmail_search",
        description: str = "Search, read, draft, and send Gmail messages from a configured Google account.",
        prompt: str | None = None,
    ) -> None:
        self.credential_key = credential_key
        self.credential_store = credential_store
        self.name = name
        self.description = description
        self.prompt = prompt or GMAIL_PROMPT
        self.prompt_instructions = "Use this for inbox search, message lookup, labels, drafts, sending email, and Gmail thread context."

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
                            "enum": [
                                "search",
                                "read_message",
                                "read_thread",
                                "get_attachment",
                                "list_labels",
                                "create_draft",
                                "send_message",
                            ],
                            "description": "Gmail action to perform",
                            "default": "search",
                        },
                        "query": {
                            "type": "string",
                            "description": 'Gmail query like "from:john unread" or "invoice"',
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 10,
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Message ID for read_message",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread ID for read_thread",
                        },
                        "attachment_id": {
                            "type": "string",
                            "description": "Attachment ID for get_attachment",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Attachment filename for display",
                        },
                        "include_body": {
                            "type": "boolean",
                            "description": "Include decoded body content in the response",
                            "default": True,
                        },
                        "include_attachments": {
                            "type": "boolean",
                            "description": "Include attachment metadata in the response",
                            "default": True,
                        },
                        "to": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Recipient email list",
                        },
                        "cc": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "CC email list",
                        },
                        "bcc": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "BCC email list",
                        },
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body content"},
                    },
                    "required": ["action"],
                },
            },
        }

    def _resolve_store(self, context: ToolContext) -> CredentialStore | None:
        shared = context.state.get("credential_store")
        if shared is not None:
            return shared
        return self.credential_store

    def _build_google_creds(self, credentials: dict[str, Any]) -> Any:
        from google.oauth2.credentials import Credentials

        tokens = credentials.get("google_tokens", credentials)
        return Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id"),
            client_secret=tokens.get("client_secret"),
        )

    def _build_service(self, record) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Install `google-api-python-client` and `google-auth` to use GmailTool."
            ) from exc

        creds = self._build_google_creds(record.secrets)
        return build("gmail", "v1", credentials=creds)

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        store = self._resolve_store(context)
        if store is None:
            return ToolOutput(
                text="No credential store configured for Gmail.",
                metadata={"provider": "gmail", "connected": False},
            )

        record = store.get(self.credential_key)
        if record is None:
            return ToolOutput(
                text="Gmail is not connected. Configure a Gmail credential record first.",
                metadata={
                    "provider": "gmail",
                    "connected": False,
                    "credential_key": self.credential_key,
                },
            )

        action = str(kwargs.get("action", "search")).strip().lower()
        service = self._build_service(record)

        handlers = {
            "search": self._search_messages,
            "read_message": self._read_message,
            "read_thread": self._read_thread,
            "get_attachment": self._get_attachment,
            "list_labels": self._list_labels,
            "create_draft": self._create_draft_or_send,
            "send_message": self._create_draft_or_send,
        }
        handler = handlers.get(action)
        if handler is not None:
            return handler(service, action, kwargs)

        raise ValueError(f"Unsupported Gmail action: {action}")
