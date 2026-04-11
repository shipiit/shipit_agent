from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from shipit_agent.integrations import CredentialStore
from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import GMAIL_PROMPT


class GmailTool:
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

    def _gmail_query(self, query: str) -> str:
        query_lower = query.lower()
        gmail_query = query
        if "unread" in query_lower:
            gmail_query = f"is:unread {query.replace('unread', '').strip()}".strip()
        elif "recent" in query_lower or "latest" in query_lower:
            gmail_query = f"newer_than:3d {query.replace('recent', '').replace('latest', '').strip()}".strip()
        return gmail_query.strip()

    def _message_headers(self, message: dict[str, Any]) -> dict[str, str]:
        return {
            header["name"]: header["value"]
            for header in message.get("payload", {}).get("headers", [])
        }

    def _decode_base64_data(self, raw: str | None) -> str:
        if not raw:
            return ""
        padding = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(f"{raw}{padding}".encode("utf-8"))
        return decoded.decode("utf-8", errors="replace")

    def _walk_parts(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not payload:
            return []
        parts = [payload]
        nested = payload.get("parts", [])
        for part in nested:
            parts.extend(self._walk_parts(part))
        return parts

    def _extract_message_content(self, message: dict[str, Any]) -> dict[str, Any]:
        payload = message.get("payload", {})
        plain_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[dict[str, Any]] = []

        for part in self._walk_parts(payload):
            mime_type = str(part.get("mimeType", ""))
            body = part.get("body", {})
            data = self._decode_base64_data(body.get("data"))

            if mime_type == "text/plain" and data:
                plain_parts.append(data)
            elif mime_type == "text/html" and data:
                html_parts.append(data)

            attachment_id = body.get("attachmentId")
            filename = str(part.get("filename", "")).strip()
            if attachment_id or filename:
                attachments.append(
                    {
                        "attachment_id": attachment_id,
                        "filename": filename or attachment_id or "attachment",
                        "mime_type": mime_type or "application/octet-stream",
                        "size": body.get("size"),
                        "part_id": part.get("partId"),
                    }
                )

        if not plain_parts and payload.get("body", {}).get("data"):
            plain_parts.append(self._decode_base64_data(payload["body"]["data"]))

        return {
            "body_text": "\n\n".join(
                item.strip() for item in plain_parts if item.strip()
            ).strip(),
            "body_html": "\n".join(
                item.strip() for item in html_parts if item.strip()
            ).strip(),
            "attachments": attachments,
        }

    def _message_preview(
        self, message: dict[str, Any], message_id: str
    ) -> dict[str, Any]:
        headers = self._message_headers(message)
        return {
            "id": message_id,
            "thread_id": message.get("threadId"),
            "subject": headers.get("Subject", "(No Subject)"),
            "from": headers.get("From", "?"),
            "to": headers.get("To", "?"),
            "date": headers.get("Date", "?"),
            "snippet": message.get("snippet", ""),
            "labels": message.get("labelIds", []),
            "url": f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
        }

    def _format_preview(self, item: dict[str, Any]) -> str:
        return (
            f"Subject: {item['subject']}\n"
            f"From: {item['from']}\n"
            f"To: {item['to']}\n"
            f"Date: {item['date']}\n"
            f"Preview: {item['snippet']}\n"
            f"Thread: {item.get('thread_id', '?')}\n"
            f"URL: {item['url']}"
        )

    def _format_detailed_message(
        self, item: dict[str, Any], *, include_body: bool, include_attachments: bool
    ) -> str:
        lines = [self._format_preview(item)]
        if include_body:
            body_text = str(item.get("body_text", "")).strip()
            body_html = str(item.get("body_html", "")).strip()
            if body_text:
                lines.append(f"Body:\n{body_text}")
            elif body_html:
                lines.append(f"HTML Body:\n{body_html}")
        if include_attachments and item.get("attachments"):
            attachment_lines = [
                f"- {attachment.get('filename', 'attachment')} [{attachment.get('mime_type', 'application/octet-stream')}] ({attachment.get('attachment_id', '?')})"
                for attachment in item["attachments"]
            ]
            lines.append("Attachments:\n" + "\n".join(attachment_lines))
        return "\n\n".join(lines)

    def _build_detailed_item(
        self, message: dict[str, Any], message_id: str
    ) -> dict[str, Any]:
        preview = self._message_preview(message, message_id)
        details = self._extract_message_content(message)
        return {
            **preview,
            "body_text": details["body_text"],
            "body_html": details["body_html"],
            "attachments": details["attachments"],
        }

    def _format_attachment_output(
        self,
        *,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
        raw_bytes: bytes,
    ) -> ToolOutput:
        preview_text = raw_bytes.decode("utf-8", errors="replace")
        preview_snippet = preview_text[:400]
        metadata: dict[str, Any] = {
            "provider": "gmail",
            "connected": True,
            "action": "get_attachment",
            "message_id": message_id,
            "attachment_id": attachment_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(raw_bytes),
            "credential_key": self.credential_key,
        }
        if preview_text.strip():
            metadata["text_preview"] = preview_snippet
            text = (
                f"Attachment: {filename}\n"
                f"Message: {message_id}\n"
                f"Mime-Type: {mime_type}\n"
                f"Size: {len(raw_bytes)} bytes\n"
                f"Preview:\n{preview_snippet}"
            )
        else:
            encoded = base64.b64encode(raw_bytes).decode("utf-8")
            metadata["content_base64"] = encoded
            text = (
                f"Attachment: {filename}\n"
                f"Message: {message_id}\n"
                f"Mime-Type: {mime_type}\n"
                f"Size: {len(raw_bytes)} bytes\n"
                "Attachment content is binary. See metadata.content_base64."
            )
        return ToolOutput(text=text, metadata=metadata)

    def _encode_email(
        self, *, to: list[str], cc: list[str], bcc: list[str], subject: str, body: str
    ) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message["Subject"] = subject
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

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

        if action == "search":
            query = str(kwargs.get("query", "")).strip()
            max_results = int(kwargs.get("max_results", 10))
            gmail_query = self._gmail_query(query)
            results = (
                service.users()
                .messages()
                .list(userId="me", q=gmail_query, maxResults=max_results)
                .execute()
            )
            messages = results.get("messages", [])
            if not messages:
                return ToolOutput(
                    text=f"No Gmail messages found for: {query}",
                    metadata={
                        "provider": "gmail",
                        "connected": True,
                        "action": action,
                        "query": query,
                        "count": 0,
                    },
                )
            items: list[dict[str, Any]] = []
            for msg_ref in messages[:max_results]:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject", "Date"],
                    )
                    .execute()
                )
                items.append(self._message_preview(msg, msg_ref["id"]))
            return ToolOutput(
                text="\n\n".join(self._format_preview(item) for item in items),
                metadata={
                    "provider": "gmail",
                    "connected": True,
                    "action": action,
                    "query": query,
                    "effective_query": gmail_query,
                    "count": len(items),
                    "items": items,
                    "credential_key": self.credential_key,
                },
            )

        if action == "read_message":
            message_id = str(kwargs.get("message_id", "")).strip()
            if not message_id:
                return ToolOutput(
                    text="message_id is required for read_message.",
                    metadata={"provider": "gmail", "action": action},
                )
            include_body = bool(kwargs.get("include_body", True))
            include_attachments = bool(kwargs.get("include_attachments", True))
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            item = self._build_detailed_item(msg, message_id)
            return ToolOutput(
                text=self._format_detailed_message(
                    item,
                    include_body=include_body,
                    include_attachments=include_attachments,
                ),
                metadata={
                    "provider": "gmail",
                    "connected": True,
                    "action": action,
                    "item": item,
                    "credential_key": self.credential_key,
                },
            )

        if action == "read_thread":
            thread_id = str(kwargs.get("thread_id", "")).strip()
            if not thread_id:
                return ToolOutput(
                    text="thread_id is required for read_thread.",
                    metadata={"provider": "gmail", "action": action},
                )
            include_body = bool(kwargs.get("include_body", True))
            include_attachments = bool(kwargs.get("include_attachments", True))
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
            messages = thread.get("messages", [])
            items = [
                self._build_detailed_item(message, message["id"])
                for message in messages
            ]
            return ToolOutput(
                text="\n\n".join(
                    self._format_detailed_message(
                        item,
                        include_body=include_body,
                        include_attachments=include_attachments,
                    )
                    for item in items
                )
                if items
                else f"No messages found in thread {thread_id}.",
                metadata={
                    "provider": "gmail",
                    "connected": True,
                    "action": action,
                    "thread_id": thread_id,
                    "items": items,
                    "count": len(items),
                    "credential_key": self.credential_key,
                },
            )

        if action == "get_attachment":
            message_id = str(kwargs.get("message_id", "")).strip()
            attachment_id = str(kwargs.get("attachment_id", "")).strip()
            filename = (
                str(kwargs.get("filename", "")).strip() or attachment_id or "attachment"
            )
            if not message_id or not attachment_id:
                return ToolOutput(
                    text="message_id and attachment_id are required for get_attachment.",
                    metadata={"provider": "gmail", "action": action},
                )
            attachment = (
                service.users()
                .messages()
                .attachments()
                .get(
                    userId="me",
                    messageId=message_id,
                    id=attachment_id,
                )
                .execute()
            )
            raw_bytes = base64.urlsafe_b64decode(
                attachment.get("data", "").encode("utf-8")
            )
            mime_type = str(kwargs.get("mime_type", "application/octet-stream"))
            return self._format_attachment_output(
                message_id=message_id,
                attachment_id=attachment_id,
                filename=filename,
                mime_type=mime_type,
                raw_bytes=raw_bytes,
            )

        if action == "list_labels":
            labels = (
                service.users().labels().list(userId="me").execute().get("labels", [])
            )
            lines = [
                f"{label.get('name', '?')} ({label.get('id', '?')})" for label in labels
            ]
            return ToolOutput(
                text="\n".join(lines) if lines else "No Gmail labels found.",
                metadata={
                    "provider": "gmail",
                    "connected": True,
                    "action": action,
                    "labels": labels,
                    "count": len(labels),
                    "credential_key": self.credential_key,
                },
            )

        if action in {"create_draft", "send_message"}:
            to = [str(value) for value in kwargs.get("to", [])]
            cc = [str(value) for value in kwargs.get("cc", [])]
            bcc = [str(value) for value in kwargs.get("bcc", [])]
            subject = str(kwargs.get("subject", "")).strip()
            body = str(kwargs.get("body", "")).strip()
            if not to or not subject:
                return ToolOutput(
                    text="`to` and `subject` are required for Gmail draft/send actions.",
                    metadata={"provider": "gmail", "action": action},
                )
            raw = self._encode_email(to=to, cc=cc, bcc=bcc, subject=subject, body=body)
            if action == "create_draft":
                result = (
                    service.users()
                    .drafts()
                    .create(userId="me", body={"message": {"raw": raw}})
                    .execute()
                )
                return ToolOutput(
                    text=f"Draft created: {subject}",
                    metadata={
                        "provider": "gmail",
                        "connected": True,
                        "action": action,
                        "draft": result,
                        "credential_key": self.credential_key,
                    },
                )
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
            return ToolOutput(
                text=f"Email sent: {subject}",
                metadata={
                    "provider": "gmail",
                    "connected": True,
                    "action": action,
                    "message": result,
                    "credential_key": self.credential_key,
                },
            )

        raise ValueError(f"Unsupported Gmail action: {action}")
