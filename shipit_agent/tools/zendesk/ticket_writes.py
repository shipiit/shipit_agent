"""Zendesk ticket changes."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _TicketWrites:
    """Zendesk ticket changes."""

    def _create_ticket(self, *, record, action, kwargs):
        subject = str(kwargs.get("subject", "")).strip()
        body = str(kwargs.get("body", "")).strip()
        if not subject or not body:
            return ToolOutput(
                text="Zendesk: `subject` and `body` are required for create_ticket.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        ticket: dict[str, Any] = {
            "subject": subject,
            "comment": {"body": body},
        }
        requester_email = str(kwargs.get("requester_email", "")).strip()
        if requester_email:
            ticket["requester"] = {"email": requester_email}
        priority = kwargs.get("priority")
        if priority is not None and str(priority).strip():
            ticket["priority"] = str(priority)
        tags = kwargs.get("tags")
        if isinstance(tags, list) and tags:
            ticket["tags"] = [str(t) for t in tags]
        payload, err = self._request_or_error(
            record=record,
            method="POST",
            path="/api/v2/tickets",
            body={"ticket": ticket},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        created = data.get("ticket", data) or {}
        return ToolOutput(
            text=(
                f"Zendesk ticket created: #{created.get('id', '?')} "
                f"{created.get('subject', subject)}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": created,
            },
        )

    def _update_ticket(self, *, record, action, kwargs):
        ticket_id = kwargs.get("id")
        if ticket_id is None:
            return ToolOutput(
                text="Zendesk: `id` is required for update_ticket.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        ticket_fields: dict[str, Any] = {}
        for field in ("subject", "priority", "status"):
            value = kwargs.get(field)
            if value is not None and str(value).strip():
                ticket_fields[field] = str(value)
        tags = kwargs.get("tags")
        if isinstance(tags, list):
            ticket_fields["tags"] = [str(t) for t in tags]
        extra_fields = kwargs.get("fields")
        if isinstance(extra_fields, dict):
            ticket_fields.update(extra_fields)
        if not ticket_fields:
            return ToolOutput(
                text=(
                    "Zendesk: update_ticket requires at least one of "
                    "subject/priority/status/tags/fields."
                ),
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/api/v2/tickets/{int(ticket_id)}"
        payload, err = self._request_or_error(
            record=record,
            method="PUT",
            path=path,
            body={"ticket": ticket_fields},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        updated = data.get("ticket", data) or {}
        return ToolOutput(
            text=(
                f"Zendesk ticket #{int(ticket_id)} updated "
                f"({', '.join(sorted(ticket_fields.keys()))})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": updated,
                "updated_fields": sorted(ticket_fields.keys()),
            },
        )

    def _add_comment(self, *, record, action, kwargs):
        ticket_id = kwargs.get("id")
        if ticket_id is None:
            return ToolOutput(
                text="Zendesk: `id` is required for add_comment.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        body = str(kwargs.get("body", "")).strip()
        if not body:
            return ToolOutput(
                text="Zendesk: `body` is required for add_comment.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        public_raw = kwargs.get("public", True)
        public = bool(public_raw) if public_raw is not None else True
        path = f"/api/v2/tickets/{int(ticket_id)}"
        payload, err = self._request_or_error(
            record=record,
            method="PUT",
            path=path,
            body={"ticket": {"comment": {"body": body, "public": public}}},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Comment added to Zendesk ticket #{int(ticket_id)} "
                f"({'public' if public else 'internal'})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "public": public,
                "item": data.get("ticket", data),
            },
        )

    def _close_ticket(self, *, record, action, kwargs):
        ticket_id = kwargs.get("id")
        if ticket_id is None:
            return ToolOutput(
                text="Zendesk: `id` is required for close_ticket.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/api/v2/tickets/{int(ticket_id)}"
        payload, err = self._request_or_error(
            record=record,
            method="PUT",
            path=path,
            body={"ticket": {"status": "closed"}},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        ticket = data.get("ticket", data) or {}
        return ToolOutput(
            text=(
                f"Closed Zendesk ticket #{int(ticket_id)} "
                f"({ticket.get('status', 'closed')})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": ticket,
            },
        )
