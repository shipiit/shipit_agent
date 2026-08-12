"""LinkedIn read-only lookup tool.

This tool is deliberately and verifiably read-only. It exposes profile and company
lookups plus discovery search, and nothing else. There is no action in the schema
that sends connection requests, InMails, messages, endorsements, or performs any
other write — the model literally cannot request one.

Users point it at LinkedIn's official API (Partner Program) or a third-party
enrichment vendor like Proxycurl or RapidAPI via the `base_url` metadata on the
credential record. Three auth shapes are supported:

* ``bearer`` (default) — ``Authorization: Bearer <token>``
* ``api_key_header`` — a custom header carrying the token (e.g. ``X-RapidAPI-Key``)
* ``query_param`` — the token is appended as ``?api_key=<token>`` on every request

Writes / automation / scraping are explicitly out of scope so the tool stays on
the right side of LinkedIn's Terms of Service.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .prompt import LINKEDIN_SEARCH_PROMPT


# READ-ONLY actions only. No write / messaging / connection action is permitted.
_ACTIONS: tuple[str, ...] = (
    "lookup_profile",
    "lookup_company",
    "search_people",
    "search_companies",
    "list_company_employees",
)

_DEFAULT_API_KEY_QUERY_PARAM = "api_key"


class LinkedInSearchTool(HTTPConnectorToolBase):
    """Read-only LinkedIn lookup.

    No messaging, connection requests, endorsements, or other automation.
    This is a deliberate product boundary to keep agents compliant with
    LinkedIn's Terms of Service.
    """

    provider = "linkedin"

    def __init__(
        self,
        *,
        credential_key: str = "linkedin",
        credential_store: Any = None,
        name: str = "linkedin_search",
        description: str = (
            "Read-only LinkedIn lookup: profiles, companies, employee search. "
            "NO messaging, connection requests, or automation — this tool is "
            "intentionally read-only to keep agents compliant with LinkedIn ToS."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or LINKEDIN_SEARCH_PROMPT
        self.prompt_instructions = (
            "Use this for read-only LinkedIn lookups: profiles, companies, and "
            "public people/company search. This tool cannot send messages, "
            "connection requests, or any other write action."
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
                            "default": "lookup_profile",
                        },
                        "profile_url": {"type": "string"},
                        "username": {"type": "string"},
                        "company_url": {"type": "string"},
                        "slug": {"type": "string"},
                        "query": {"type": "string"},
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "industry": {"type": "string"},
                        "size": {"type": "string"},
                        "limit": {"type": "integer", "default": 25},
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------- auth modes

    def _auth_mode(self, record: CredentialRecord) -> str:
        mode = str((record.metadata or {}).get("auth_mode", "bearer")).strip().lower()
        if mode not in {"bearer", "api_key_header", "query_param"}:
            return "bearer"
        return mode

    def _token(self, record: CredentialRecord) -> str:
        secrets = record.secrets or {}
        return str(
            secrets.get("token")
            or secrets.get("api_key")
            or secrets.get("access_token")
            or ""
        )

    def _headers(self, record: CredentialRecord) -> dict[str, str]:
        mode = self._auth_mode(record)
        token = self._token(record)

        if mode == "bearer":
            headers = {"content-type": "application/json"}
            if token:
                headers["authorization"] = f"Bearer {token}"
            extra = (record.metadata or {}).get("headers", {})
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
            return headers

        if mode == "api_key_header":
            headers = {"content-type": "application/json"}
            header_name = str(
                (record.metadata or {}).get("api_key_header", "X-API-Key")
            )
            if token:
                headers[header_name] = token
            extra = (record.metadata or {}).get("headers", {})
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
            return headers

        # query_param mode — no auth header at all; token rides on the URL.
        headers = {"content-type": "application/json"}
        extra = (record.metadata or {}).get("headers", {})
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _augment_query(
        self, record: CredentialRecord, query: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if self._auth_mode(record) != "query_param":
            return query
        param_name = str(
            (record.metadata or {}).get(
                "api_key_query_param", _DEFAULT_API_KEY_QUERY_PARAM
            )
        )
        token = self._token(record)
        merged: dict[str, Any] = dict(query or {})
        if token:
            merged[param_name] = token
        return merged

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
                record=record,
                method=method,
                path=path,
                query=self._augment_query(record, query),
                body=body,
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"LinkedIn request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        code = int(getattr(err, "code", 0) or 0)
        headers = getattr(err, "headers", None)
        retry_after: int | None = None
        if headers is not None:
            try:
                raw = headers.get("Retry-After")
                if raw is not None:
                    retry_after = int(raw)
            except (TypeError, ValueError):
                retry_after = None
        if code == 429:
            return ToolOutput(
                text=(
                    "LinkedIn rate limit exceeded."
                    + (f" Retry after {retry_after}s." if retry_after else "")
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "status": 429,
                    "retry_after": retry_after,
                },
            )

        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"LinkedIn HTTP {code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": code,
                "message": message,
            },
        )

    @staticmethod
    def _extract_error_message(err: HTTPError) -> str:
        try:
            raw = err.read()
            if raw:
                decoded = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(decoded)
                    msg = (
                        parsed.get("message")
                        or parsed.get("error")
                        or parsed.get("detail")
                    )
                    if isinstance(msg, str) and msg:
                        return msg
                except json.JSONDecodeError:
                    if decoded:
                        return decoded[:300]
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    # ----------------------------------------------------------- missing url

    def _missing_base_url_output(self) -> ToolOutput:
        return ToolOutput(
            text=(
                "LinkedIn: missing base_url on the credential record. Point it at an "
                "API vendor such as Proxycurl (https://nubela.co/proxycurl/api) or a "
                "RapidAPI LinkedIn endpoint, and set `metadata.base_url` accordingly."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "missing_base_url",
                "hint": (
                    "Configure metadata.base_url — e.g. Proxycurl "
                    "'https://nubela.co/proxycurl/api' or a RapidAPI endpoint — "
                    "and set metadata.auth_mode (bearer | api_key_header | query_param)."
                ),
            },
        )

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
        if not self._base_url(record):
            return self._missing_base_url_output()

        action = str(kwargs.get("action", "")).strip()

        handlers = {
            "lookup_profile": self._lookup_profile,
            "lookup_company": self._lookup_company,
            "search_people": self._search_people,
            "search_companies": self._search_companies,
            "list_company_employees": self._list_company_employees,
        }
        # Enforce read-only invariant defensively: if the action somehow carries
        # a write-flavored name, reject it before dispatch.
        if any(
            token in action.lower()
            for token in (
                "send",
                "message",
                "connect",
                "invite",
                "endorse",
                "follow",
                "post",
                "create",
                "update",
                "delete",
            )
        ):
            return ToolOutput(
                text=(
                    f"LinkedIn: action '{action}' is not permitted. This tool is "
                    "read-only and does not support messaging, connection, or any "
                    "write action."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "write_action_blocked",
                    "action": action,
                },
            )

        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"LinkedIn: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                    "allowed": list(_ACTIONS),
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)

    # ------------------------------------------------------------- formatters

    @staticmethod
    def _profile_card(item: dict[str, Any]) -> str:
        name = (
            item.get("full_name")
            or item.get("name")
            or (
                f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()
                or "?"
            )
        )
        headline = item.get("headline") or item.get("title") or ""
        company = (
            item.get("company")
            or item.get("current_company")
            or (item.get("experience", [{}]) or [{}])[0].get("company", "")
        )
        location = (
            item.get("location")
            or item.get("city")
            or item.get("country_full_name")
            or ""
        )
        parts = [str(name)]
        if headline:
            parts.append(f"— {headline}")
        if company:
            parts.append(f"@ {company}")
        if location:
            parts.append(f"({location})")
        return " ".join(parts)

    @staticmethod
    def _company_card(item: dict[str, Any]) -> str:
        name = item.get("name") or item.get("company_name") or "?"
        industry = item.get("industry") or ""
        size = item.get("company_size") or item.get("size") or ""
        location = item.get("hq") or item.get("location") or ""
        parts = [str(name)]
        if industry:
            parts.append(f"— {industry}")
        if size:
            parts.append(f"({size})")
        if location:
            parts.append(f"[{location}]")
        return " ".join(parts)

    @staticmethod
    def _search_line(item: dict[str, Any]) -> str:
        name = (
            item.get("full_name")
            or item.get("name")
            or (
                f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()
                or "?"
            )
        )
        title = item.get("title") or item.get("headline") or ""
        company = item.get("company") or item.get("current_company") or ""
        pieces = [str(name)]
        if title:
            pieces.append(f"— {title}")
        if company:
            pieces.append(f"@ {company}")
        return " ".join(pieces)

    # ---------------------------------------------------------- read actions

    def _lookup_profile(self, *, record, action, kwargs):
        profile_url = str(kwargs.get("profile_url", "")).strip()
        username = str(kwargs.get("username", "")).strip()
        if not profile_url and not username:
            return ToolOutput(
                text="LinkedIn: `profile_url` or `username` is required for lookup_profile.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "required": ["profile_url", "username"],
                },
            )
        query: dict[str, Any] = {}
        if profile_url:
            query["url"] = profile_url
        else:
            query["username"] = username
        payload, err = self._request_or_error(
            record=record, method="GET", path="/lookup-profile", query=query
        )
        if err is not None:
            return err
        item = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=self._profile_card(item),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": item,
            },
        )

    def _lookup_company(self, *, record, action, kwargs):
        company_url = str(kwargs.get("company_url", "")).strip()
        slug = str(kwargs.get("slug", "")).strip()
        if not company_url and not slug:
            return ToolOutput(
                text="LinkedIn: `company_url` or `slug` is required for lookup_company.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "required": ["company_url", "slug"],
                },
            )
        query: dict[str, Any] = {}
        if company_url:
            query["url"] = company_url
        else:
            query["slug"] = slug
        payload, err = self._request_or_error(
            record=record, method="GET", path="/lookup-company", query=query
        )
        if err is not None:
            return err
        item = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=self._company_card(item),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": item,
            },
        )

    def _search_people(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="LinkedIn: `query` is required for search_people.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        query: dict[str, Any] = {"query": q}
        if kwargs.get("company"):
            query["company"] = str(kwargs.get("company"))
        if kwargs.get("title"):
            query["title"] = str(kwargs.get("title"))
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        payload, err = self._request_or_error(
            record=record, method="GET", path="/search-people", query=query
        )
        if err is not None:
            return err
        items = self._extract_items(payload)
        lines = [self._search_line(item) for item in items]
        text = "\n".join(lines) if lines else "No LinkedIn profiles matched the query."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": items,
                "count": len(items),
            },
        )

    def _search_companies(self, *, record, action, kwargs):
        q = str(kwargs.get("query", "")).strip()
        if not q:
            return ToolOutput(
                text="LinkedIn: `query` is required for search_companies.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        query: dict[str, Any] = {"query": q}
        if kwargs.get("industry"):
            query["industry"] = str(kwargs.get("industry"))
        if kwargs.get("size"):
            query["size"] = str(kwargs.get("size"))
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        payload, err = self._request_or_error(
            record=record, method="GET", path="/search-companies", query=query
        )
        if err is not None:
            return err
        items = self._extract_items(payload)
        lines = [self._company_card(item) for item in items]
        text = "\n".join(lines) if lines else "No LinkedIn companies matched the query."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": items,
                "count": len(items),
            },
        )

    def _list_company_employees(self, *, record, action, kwargs):
        slug = str(kwargs.get("slug", "")).strip()
        if not slug:
            return ToolOutput(
                text="LinkedIn: `slug` is required for list_company_employees.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        query: dict[str, Any] = {"slug": slug}
        if kwargs.get("limit") is not None:
            query["limit"] = int(kwargs["limit"])
        payload, err = self._request_or_error(
            record=record, method="GET", path="/company-employees", query=query
        )
        if err is not None:
            return err
        items = self._extract_items(payload)
        lines = [self._search_line(item) for item in items]
        text = (
            "\n".join(lines)
            if lines
            else f"No employees returned for company slug '{slug}'."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "slug": slug,
                "items": items,
                "count": len(items),
            },
        )

    @staticmethod
    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("results", "items", "people", "companies", "employees", "data"):
                val = payload.get(key)
                if isinstance(val, list):
                    return [item for item in val if isinstance(item, dict)]
        return []
