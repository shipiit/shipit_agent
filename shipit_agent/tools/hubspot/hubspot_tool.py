"""`hubspot_ops` — HubSpot CRM v3 REST wrapper for sales / CS agents.

Auth: ``HUBSPOT_TOKEN`` env (a private-app bearer token from HubSpot →
Settings → Integrations → Private Apps). Every action is one HTTP call.

Actions:
  - ``search_contacts`` / ``search_companies`` / ``search_deals``
  - ``get_contact`` / ``get_company`` / ``get_deal``         (by id)
  - ``create_contact`` / ``create_deal``
  - ``add_note``    — attach a note to a contact, company, or deal
  - ``list_owners`` — look up sales reps to assign ownership

The tool is deliberately read-biased: writes are flagged ``destructive``
so the harness's HITL layer can gate them.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


API = "https://api.hubapi.com"


class HubspotTool:
    name = "hubspot_ops"
    description = "HubSpot CRM v3 — search/get/create contacts, companies, deals; attach notes."
    prompt_instructions = (
        "Call hubspot_ops with one action at a time. For writes (create/add_note) "
        "remember to pass the correct object_type for note attachment."
    )

    WRITE_ACTIONS = frozenset({"create_contact", "create_deal", "add_note"})

    def __init__(self, *, token: str | None = None) -> None:
        self.token = token or os.environ.get("HUBSPOT_TOKEN")
        self.prompt = self.prompt_instructions

    # ── schema ──────────────────────────────────────────────────

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": [
                            "search_contacts", "search_companies", "search_deals",
                            "get_contact", "get_company", "get_deal",
                            "create_contact", "create_deal",
                            "add_note", "list_owners",
                        ]},
                        "query": {"type": "string", "description": "Free-text search query."},
                        "object_id": {"type": "string"},
                        "object_type": {"type": "string", "enum": ["contact", "company", "deal"]},
                        "properties": {"type": "object"},
                        "note": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["action"],
                },
            },
        }

    # ── run ─────────────────────────────────────────────────────

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        if not self.token:
            return ToolOutput(
                text="Error: HUBSPOT_TOKEN not set (private-app bearer token).",
                metadata={"ok": False},
            )
        action = str(kwargs.get("action", "")).strip().lower()
        try:
            if action in ("search_contacts", "search_companies", "search_deals"):
                obj = action.split("_", 1)[1][:-1]
                return self._search(obj, kwargs.get("query", ""), int(kwargs.get("limit", 10)))
            if action in ("get_contact", "get_company", "get_deal"):
                obj = action.split("_", 1)[1]
                oid = str(kwargs.get("object_id", ""))
                if not oid:
                    return ToolOutput(text="Error: object_id is required.", metadata={"ok": False})
                return self._get(obj, oid)
            if action == "create_contact":
                return self._create("contact", kwargs.get("properties") or {})
            if action == "create_deal":
                return self._create("deal", kwargs.get("properties") or {})
            if action == "add_note":
                return self._add_note(kwargs)
            if action == "list_owners":
                return self._list_owners()
        except HubspotError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})
        return ToolOutput(text=f"Error: unknown action {action!r}.", metadata={"ok": False})

    # ── concrete actions ────────────────────────────────────────

    def _search(self, obj: str, query: str, limit: int) -> ToolOutput:
        body = {"query": query, "limit": max(1, min(limit, 100))}
        data = self._request("POST", f"/crm/v3/objects/{obj}s/search", body=body)
        results = data.get("results") or []
        lines = [f"{obj} {r.get('id')} — {self._summary(obj, r)}" for r in results]
        return ToolOutput(text="\n".join(lines) or "(no results)", metadata={"ok": True, "count": len(results)})

    def _get(self, obj: str, oid: str) -> ToolOutput:
        data = self._request("GET", f"/crm/v3/objects/{obj}s/{oid}")
        return ToolOutput(text=json.dumps(data, indent=2), metadata={"ok": True})

    def _create(self, obj: str, properties: dict[str, Any]) -> ToolOutput:
        if not properties:
            return ToolOutput(text="Error: properties object is required.", metadata={"ok": False})
        data = self._request("POST", f"/crm/v3/objects/{obj}s", body={"properties": properties})
        return ToolOutput(text=f"Created {obj} {data.get('id')}.", metadata={"ok": True, "id": data.get("id")})

    def _add_note(self, kwargs: dict[str, Any]) -> ToolOutput:
        note = str(kwargs.get("note", "")).strip()
        oid = str(kwargs.get("object_id", ""))
        obj_type = str(kwargs.get("object_type", ""))
        if not note or not oid or not obj_type:
            return ToolOutput(text="Error: note, object_id, and object_type required.", metadata={"ok": False})

        # v3 notes: create Note, then associate with target via /associations.
        body = {
            "properties": {"hs_note_body": note, "hs_timestamp": "now"},
        }
        note_data = self._request("POST", "/crm/v3/objects/notes", body=body)
        note_id = note_data.get("id")
        if note_id:
            self._request("PUT",
                f"/crm/v3/objects/notes/{note_id}/associations/{obj_type}s/{oid}/note_to_{obj_type}",
                body={})
        return ToolOutput(text=f"Added note {note_id} to {obj_type} {oid}.", metadata={"ok": True, "note_id": note_id})

    def _list_owners(self) -> ToolOutput:
        data = self._request("GET", "/crm/v3/owners?limit=100")
        owners = data.get("results") or []
        lines = [f"{o.get('id')} — {o.get('email')} ({o.get('firstName','')} {o.get('lastName','')})" for o in owners]
        return ToolOutput(text="\n".join(lines) or "(no owners)", metadata={"ok": True, "count": len(owners)})

    @staticmethod
    def _summary(obj: str, r: dict[str, Any]) -> str:
        props = r.get("properties") or {}
        if obj == "contact":
            return f"{props.get('email','?')} — {props.get('firstname','')} {props.get('lastname','')}"
        if obj == "company":
            return f"{props.get('name','?')} — domain={props.get('domain','?')}"
        if obj == "deal":
            return f"{props.get('dealname','?')} — stage={props.get('dealstage','?')} amt={props.get('amount','?')}"
        return "(summary unavailable)"

    # ── transport ───────────────────────────────────────────────

    def _request(self, method: str, path: str, *, body: Any = None) -> dict[str, Any]:
        url = f"{API}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "ignore") if err.fp else ""
            raise HubspotError(f"HubSpot {err.code}: {text[:300]}") from err
        except urllib.error.URLError as err:
            raise HubspotError(f"Network error: {err}") from err


class HubspotError(RuntimeError):
    pass
