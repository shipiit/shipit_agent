"""Zendesk ticket lookups."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _TicketReads:
    """Zendesk ticket lookups."""

    def _search_tickets(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="Zendesk: `query` is required for search_tickets.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        query_params: dict[str, Any] = {"query": q}
        if kwargs.get("per_page") is not None:
            query_params["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query_params["page"] = int(kwargs["page"])
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/api/v2/search.json",
            query=query_params,
        )
        if err is not None:
            return err
        results = (
            payload.get("results", []) if isinstance(payload, dict) else []
        )
        lines = [self._ticket_line(item) for item in results]
        text = "\n".join(lines) if lines else "No Zendesk tickets matched the query."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": results,
                "count": len(results),
                "total_count": (
                    payload.get("count") if isinstance(payload, dict) else None
                ),
            },
        )

    def _get_ticket(self, *, record, action, kwargs):
        ticket_id = kwargs.get("id")
        if ticket_id is None:
            return ToolOutput(
                text="Zendesk: `id` is required for get_ticket.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/api/v2/tickets/{int(ticket_id)}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        ticket = data.get("ticket", data) or {}
        requester = ticket.get("requester") or {}
        tags = ticket.get("tags") or []
        last_comment = ""
        comments = ticket.get("comments")
        if isinstance(comments, list) and comments:
            last = comments[-1]
            if isinstance(last, dict):
                last_comment = str(last.get("body", ""))[:200]
        text_lines = [
            f"#{ticket.get('id', ticket_id)} [{ticket.get('status', '?')}] "
            f"{ticket.get('subject', '')}",
            f"Priority: {ticket.get('priority', '?')}",
            (
                f"Requester: {requester.get('name', '?')} "
                f"<{requester.get('email', '?')}>"
            ),
            f"Tags: {', '.join(str(t) for t in tags) if tags else 'none'}",
        ]
        if last_comment:
            text_lines.append(f"Last comment: {last_comment}")
        return ToolOutput(
            text="\n".join(text_lines),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": ticket,
            },
        )

    def _list_tickets(self, *, record, action, kwargs):
        query: dict[str, Any] = {}
        if kwargs.get("per_page") is not None:
            query["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query["page"] = int(kwargs["page"])
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/api/v2/tickets.json",
            query=query or None,
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        tickets = data.get("tickets", []) or []
        lines = [self._ticket_line(t) for t in tickets]
        text = "\n".join(lines) if lines else "No Zendesk tickets found."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": tickets,
                "count": len(tickets),
                "total_count": data.get("count"),
            },
        )
