"""Gmail message parsing and formatting: headers, parts, previews, attachments and MIME encoding."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from shipit_agent.tools.base import ToolOutput


class _MessageFormatting:
    """Gmail message parsing and formatting: headers, parts, previews, attachments and MIME encoding."""

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
