"""Zendesk user and macro actions."""

from __future__ import annotations

from shipit_agent.tools.base import ToolOutput


class _UserMacroActions:
    """Zendesk user and macro actions."""

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
