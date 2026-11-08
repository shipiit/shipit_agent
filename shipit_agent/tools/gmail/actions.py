"""Gmail actions: search, read, attachments, labels, drafts and sending."""

from __future__ import annotations

import base64
from typing import Any

from shipit_agent.tools.base import ToolOutput


class _GmailActions:
    """Gmail actions: search, read, attachments, labels, drafts and sending."""

    def _search_messages(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _read_message(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _read_thread(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _get_attachment(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _list_labels(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _create_draft_or_send(
        self, service: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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
