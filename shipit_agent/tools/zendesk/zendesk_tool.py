from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import ZENDESK_PROMPT

_ACTIONS = [
    "search_tickets",
    "get_ticket",
    "create_ticket",
    "update_ticket",
    "add_comment",
    "close_ticket",
    "list_tickets",
    "get_user",
    "search_users",
    "list_macros",
    "apply_macro",
]

_WRITE_GATED_ACTIONS = {"create_ticket", "update_ticket", "close_ticket"}


class ZendeskTool(HTTPConnectorToolBase):
    provider = "zendesk"

    def __init__(
        self,
        *,
        credential_key: str = "zendesk",
        credential_store: Any = None,
        allow_writes: bool = False,
        name: str = "zendesk",
        description: str = (
            "Search / read / comment on Zendesk tickets and users; list and "
            "preview macros."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.allow_writes = allow_writes
        self.name = name
        self.description = description
        self.prompt = prompt or ZENDESK_PROMPT
        self.prompt_instructions = (
            "Use this for Zendesk ticket triage, customer support lookups, "
            "adding comments, and previewing macros."
        )

    # ------------------------------------------------------------------ schema

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
                            "enum": list(_ACTIONS),
                            "default": "search_tickets",
                        },
                        "id": {"type": "integer"},
                        "macro_id": {"type": "integer"},
                        "query": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "requester_email": {"type": "string"},
                        "priority": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "fields": {
                            "type": "object",
                            "description": (
                                "Arbitrary ticket fields for update_ticket "
                                "(merged into the nested `ticket` body)."
                            ),
                        },
                        "public": {"type": "boolean", "default": True},
                        "per_page": {"type": "integer", "default": 100},
                        "page": {"type": "integer", "default": 1},
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------ auth

    def _credential_email(self, record: CredentialRecord) -> str:
        return str(
            (record.secrets or {}).get("email")
            or (record.metadata or {}).get("email")
            or ""
        ).strip()

    def _credential_token(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("api_token")
            or secrets.get("token")
            or ""
        ).strip()

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json"}
        email = self._credential_email(record)
        token = self._credential_token(record)
        if email and token:
            raw = f"{email}/token:{token}".encode("utf-8")
            encoded = base64.b64encode(raw).decode("ascii")
            headers["authorization"] = f"Basic {encoded}"
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    # ------------------------------------------------------------------ URL

    def _missing_subdomain_output(self) -> ToolOutput:
        return ToolOutput(
            text=(
                "Zendesk: missing subdomain. Set `metadata.base_url = "
                "https://{subdomain}.zendesk.com` on the credential record."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "missing_subdomain",
                "hint": "metadata.base_url = https://{subdomain}.zendesk.com",
            },
        )

    # ---------------------------------------------------------- HTTP wrapper

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        try:
            payload = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"Zendesk request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        if err.code == 429:
            retry_after_seconds = 0
            headers = getattr(err, "headers", None)
            if headers is not None:
                try:
                    raw = headers.get("Retry-After")
                    if raw is not None:
                        retry_after_seconds = int(raw)
                except (TypeError, ValueError):
                    retry_after_seconds = 0
            return ToolOutput(
                text=(
                    "Zendesk rate limit exceeded. Retry after "
                    f"{retry_after_seconds} seconds."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after_seconds": retry_after_seconds,
                    "status": 429,
                },
            )
        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"Zendesk HTTP {err.code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": int(err.code),
                "message": message,
            },
        )

    @staticmethod
    def _extract_error_message(err: HTTPError) -> str:
        try:
            raw = err.read()
            if raw:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                description = parsed.get("description")
                if isinstance(description, str) and description:
                    return description
                error_name = parsed.get("error")
                if isinstance(error_name, str) and error_name:
                    return error_name
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    # --------------------------------------------------------------- helpers

    def _writes_disabled_output(self, action: str) -> ToolOutput:
        return ToolOutput(
            text=(
                f"Zendesk: action '{action}' requires allow_writes=True. "
                "Construct ZendeskTool(allow_writes=True) to enable writes."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "writes_disabled",
                "action": action,
            },
        )

    @staticmethod
    def _ticket_line(ticket: dict[str, Any]) -> str:
        tid = ticket.get("id", "?")
        status = ticket.get("status", "?")
        subject = ticket.get("subject", "")
        url = ticket.get("url", "")
        return f"#{tid} [{status}] {subject}  {url}".rstrip()

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)

        action = str(kwargs.get("action", "search_tickets")).strip()

        if action in _WRITE_GATED_ACTIONS and not self.allow_writes:
            return self._writes_disabled_output(action)

        if not self._base_url(record):
            return self._missing_subdomain_output()

        handlers = {
            "search_tickets": self._search_tickets,
            "get_ticket": self._get_ticket,
            "create_ticket": self._create_ticket,
            "update_ticket": self._update_ticket,
            "add_comment": self._add_comment,
            "close_ticket": self._close_ticket,
            "list_tickets": self._list_tickets,
            "get_user": self._get_user,
            "search_users": self._search_users,
            "list_macros": self._list_macros,
            "apply_macro": self._apply_macro,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Zendesk: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ---------------------------------------------------------- ticket actions

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

    # ---------------------------------------------------------- user actions

    def _get_user(self, *, record, action, kwargs):
        user_id = kwargs.get("id")
        if user_id is None:
            return ToolOutput(
                text="Zendesk: `id` is required for get_user.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/api/v2/users/{int(user_id)}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        user = data.get("user", data) or {}
        text = (
            f"{user.get('name', '?')} <{user.get('email', '?')}> "
            f"(id={user.get('id', user_id)}, role={user.get('role', '?')})"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": user,
            },
        )

    def _search_users(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="Zendesk: `query` is required for search_users.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/api/v2/users/search.json",
            query={"query": q},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        users = data.get("users", []) or []
        lines = [
            f"{u.get('id', '?')}: {u.get('name', '?')} <{u.get('email', '?')}>"
            for u in users
        ]
        text = "\n".join(lines) if lines else "No Zendesk users matched the query."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": users,
                "count": len(users),
            },
        )

    # --------------------------------------------------------- macro actions

    def _list_macros(self, *, record, action, kwargs):
        payload, err = self._request_or_error(
            record=record,
            method="GET",
            path="/api/v2/macros.json",
            query={"access": "personal"},
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        macros = data.get("macros", []) or []
        lines = [
            f"{m.get('id', '?')}: {m.get('title', '?')}"
            for m in macros
        ]
        text = "\n".join(lines) if lines else "No Zendesk macros found."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": macros,
                "count": len(macros),
            },
        )

    def _apply_macro(self, *, record, action, kwargs):
        ticket_id = kwargs.get("id")
        macro_id = kwargs.get("macro_id")
        if ticket_id is None or macro_id is None:
            return ToolOutput(
                text="Zendesk: `id` and `macro_id` are required for apply_macro.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/api/v2/tickets/{int(ticket_id)}/macros/{int(macro_id)}/apply"
        )
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        preview = data.get("result") or data
        return ToolOutput(
            text=(
                f"Macro {int(macro_id)} preview for ticket "
                f"#{int(ticket_id)} (not persisted)."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "preview": preview,
                "ticket_id": int(ticket_id),
                "macro_id": int(macro_id),
            },
        )
