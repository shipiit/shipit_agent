"""LinkedIn profile, company and people-search actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _LookupActions:
    """LinkedIn profile, company and people-search actions."""

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
