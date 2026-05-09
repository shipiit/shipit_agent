from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.linkedin import LINKEDIN_SEARCH_PROMPT, LinkedInSearchTool
from shipit_agent.tools.linkedin.linkedin_search_tool import _ACTIONS


# ---------------------------------------------------------------- helpers


def _store_bearer(token="pxl_demo"):
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="linkedin",
            provider="linkedin",
            secrets={"token": token},
            metadata={
                "base_url": "https://nubela.co/proxycurl/api",
                "auth_mode": "bearer",
            },
        )
    )
    return s


def _store_rapidapi(key="rapid_demo"):
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="linkedin",
            provider="linkedin",
            secrets={"token": key},
            metadata={
                "base_url": "https://linkedin-api.p.rapidapi.com",
                "auth_mode": "api_key_header",
                "api_key_header": "X-RapidAPI-Key",
            },
        )
    )
    return s


def _store_query_param(token="q_demo"):
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="linkedin",
            provider="linkedin",
            secrets={"token": token},
            metadata={
                "base_url": "https://vendor.example.com/api",
                "auth_mode": "query_param",
            },
        )
    )
    return s


def _store_no_base_url():
    s = InMemoryCredentialStore()
    s.set(
        CredentialRecord(
            key="linkedin",
            provider="linkedin",
            secrets={"token": "t"},
            metadata={"auth_mode": "bearer"},
        )
    )
    return s


def _ctx(store=None):
    state = {}
    if store is not None:
        state["credential_store"] = store
    return ToolContext(prompt="test", state=state)


def _capture(payload):
    captured: list[dict] = []

    def fake(*, record, method, path, query=None, body=None):
        captured.append(
            {
                "record": record,
                "method": method,
                "path": path,
                "query": query,
                "body": body,
            }
        )
        return payload

    return captured, fake


def _http_error(code: int, body: bytes = b'{"message":"Boom"}', headers=None):
    return HTTPError(
        url="https://vendor.example.com/fake",
        code=code,
        msg="boom",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


# ---------------------------------------------------------------- metadata


def test_tool_shape_and_prompt():
    tool = LinkedInSearchTool()
    assert tool.name == "linkedin_search"
    assert tool.provider == "linkedin"
    assert "read-only" in tool.description.lower()
    assert LINKEDIN_SEARCH_PROMPT in tool.prompt
    assert "no" in tool.description.lower() and "messaging" in tool.description.lower()


def test_schema_enum_is_read_only():
    enum = LinkedInSearchTool().schema()["function"]["parameters"]["properties"][
        "action"
    ]["enum"]
    assert set(enum) == {
        "lookup_profile",
        "lookup_company",
        "search_people",
        "search_companies",
        "list_company_employees",
    }
    assert set(enum) == set(_ACTIONS)


def test_schema_contains_no_write_actions():
    enum = LinkedInSearchTool().schema()["function"]["parameters"]["properties"][
        "action"
    ]["enum"]
    forbidden_substrings = (
        "send",
        "message",
        "connect",
        "invite",
        "endorse",
        "follow",
        "create",
        "update",
        "delete",
        "post",
        "inmail",
    )
    for action in enum:
        lowered = action.lower()
        for bad in forbidden_substrings:
            assert bad not in lowered, (
                f"Action '{action}' contains forbidden token '{bad}' — tool must stay read-only"
            )


# ---------------------------------------------------------------- guard rails


def test_not_connected_without_credential_store():
    tool = LinkedInSearchTool()
    out = tool.run(context=ToolContext(prompt="x"), action="lookup_profile")
    assert out.metadata["connected"] is False
    assert "not connected" in out.text.lower()


def test_missing_base_url_surfaces_hint():
    tool = LinkedInSearchTool(credential_store=_store_no_base_url())
    out = tool.run(context=_ctx(_store_no_base_url()), action="lookup_profile")
    assert out.metadata["error"] == "missing_base_url"
    assert "base_url" in out.text.lower() or "proxycurl" in out.text.lower()
    assert "proxycurl" in out.metadata["hint"].lower()


def test_unknown_action_returns_structured_error():
    tool = LinkedInSearchTool(credential_store=_store_bearer())
    out = tool.run(context=_ctx(_store_bearer()), action="flergle")
    assert out.metadata["error"] == "unsupported_action"
    assert "flergle" in out.text


def test_blocked_write_action_even_if_injected():
    # Defensive check: even if someone tries to smuggle a write action through,
    # the runtime rejects it before dispatch.
    tool = LinkedInSearchTool(credential_store=_store_bearer())
    for bad in ("send_message", "connect_user", "invite_connection", "create_post"):
        out = tool.run(context=_ctx(_store_bearer()), action=bad)
        assert out.metadata["error"] == "write_action_blocked", bad


# ---------------------------------------------------------------- auth modes


def test_bearer_auth_sets_authorization_header():
    tool = LinkedInSearchTool(credential_store=_store_bearer("pxl_xyz"))
    record = _store_bearer("pxl_xyz").get("linkedin")
    headers = tool._headers(record)
    assert headers["authorization"] == "Bearer pxl_xyz"
    assert "x-rapidapi-key" not in {k.lower() for k in headers}


def test_api_key_header_auth_uses_custom_header_and_no_authorization():
    store = _store_rapidapi("rapid_xyz")
    tool = LinkedInSearchTool(credential_store=store)
    record = store.get("linkedin")
    headers = tool._headers(record)
    assert headers["X-RapidAPI-Key"] == "rapid_xyz"
    assert "authorization" not in {k.lower() for k in headers}


def test_query_param_auth_appends_api_key_to_every_request():
    store = _store_query_param("q_xyz")
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture({"full_name": "Ada Lovelace"})
    tool._request_json = fake  # type: ignore[assignment]
    tool.run(
        context=_ctx(store),
        action="lookup_profile",
        profile_url="https://linkedin.com/in/ada",
    )
    assert captured[0]["query"]["api_key"] == "q_xyz"
    assert captured[0]["query"]["url"] == "https://linkedin.com/in/ada"
    # Also verify no auth header leaks into request headers for this mode.
    record = store.get("linkedin")
    headers = tool._headers(record)
    assert "authorization" not in {k.lower() for k in headers}


# ---------------------------------------------------------------- lookups


def test_lookup_profile_by_url():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture(
        {
            "full_name": "Ada Lovelace",
            "headline": "Mathematician",
            "company": "Analytical Engines Inc.",
            "location": "London, UK",
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(store),
        action="lookup_profile",
        profile_url="https://linkedin.com/in/ada",
    )
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/lookup-profile"
    assert call["query"] == {"url": "https://linkedin.com/in/ada"}
    assert "Ada Lovelace" in out.text
    assert "Mathematician" in out.text
    assert "Analytical Engines" in out.text
    assert "London" in out.text


def test_lookup_profile_by_username():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture({"full_name": "Grace Hopper", "headline": "Admiral"})
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(context=_ctx(store), action="lookup_profile", username="grace")
    assert captured[0]["query"] == {"username": "grace"}
    assert "Grace Hopper" in out.text


def test_lookup_profile_missing_params():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    out = tool.run(context=_ctx(store), action="lookup_profile")
    assert out.metadata["error"] == "missing_parameter"


def test_lookup_company_by_url_and_slug():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)

    captured_url, fake_url = _capture(
        {"name": "OpenAI", "industry": "AI", "company_size": "1001-5000", "hq": "SF"}
    )
    tool._request_json = fake_url  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(store),
        action="lookup_company",
        company_url="https://linkedin.com/company/openai",
    )
    assert captured_url[0]["path"] == "/lookup-company"
    assert captured_url[0]["query"] == {"url": "https://linkedin.com/company/openai"}
    assert "OpenAI" in out.text
    assert "AI" in out.text
    assert "SF" in out.text

    captured_slug, fake_slug = _capture({"name": "Anthropic", "industry": "AI"})
    tool._request_json = fake_slug  # type: ignore[assignment]
    tool.run(context=_ctx(store), action="lookup_company", slug="anthropic")
    assert captured_slug[0]["query"] == {"slug": "anthropic"}


# ---------------------------------------------------------------- search


def test_search_people_with_all_params():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture(
        {
            "results": [
                {
                    "full_name": "Ada Lovelace",
                    "title": "Engineer",
                    "company": "Analytical Engines Inc.",
                },
                {
                    "full_name": "Grace Hopper",
                    "title": "Admiral",
                    "company": "USN",
                },
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(store),
        action="search_people",
        query="pioneers",
        company="Analytical Engines",
        title="Engineer",
        limit=10,
    )
    assert captured[0]["path"] == "/search-people"
    assert captured[0]["query"] == {
        "query": "pioneers",
        "company": "Analytical Engines",
        "title": "Engineer",
        "limit": 10,
    }
    assert "Ada Lovelace" in out.text
    assert "Grace Hopper" in out.text
    assert out.metadata["count"] == 2


def test_search_companies():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture(
        {
            "results": [
                {
                    "name": "OpenAI",
                    "industry": "AI",
                    "company_size": "1001-5000",
                    "hq": "SF",
                },
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(store),
        action="search_companies",
        query="AI labs",
        industry="Artificial Intelligence",
        size="1001-5000",
        limit=5,
    )
    assert captured[0]["path"] == "/search-companies"
    assert captured[0]["query"] == {
        "query": "AI labs",
        "industry": "Artificial Intelligence",
        "size": "1001-5000",
        "limit": 5,
    }
    assert "OpenAI" in out.text
    assert out.metadata["count"] == 1


def test_list_company_employees():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)
    captured, fake = _capture(
        {
            "employees": [
                {"full_name": "Alice", "title": "CEO", "company": "Acme"},
                {"full_name": "Bob", "title": "CTO", "company": "Acme"},
            ]
        }
    )
    tool._request_json = fake  # type: ignore[assignment]
    out = tool.run(
        context=_ctx(store),
        action="list_company_employees",
        slug="acme",
        limit=50,
    )
    assert captured[0]["path"] == "/company-employees"
    assert captured[0]["query"] == {"slug": "acme", "limit": 50}
    assert "Alice" in out.text
    assert "Bob" in out.text
    assert out.metadata["slug"] == "acme"
    assert out.metadata["count"] == 2


# ---------------------------------------------------------------- errors


def test_rate_limit_429_returns_structured_error():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)

    def raise_429(**_kwargs):
        raise _http_error(
            429,
            body=b'{"message":"slow down"}',
            headers={"Retry-After": "30"},
        )

    tool._request_json = raise_429  # type: ignore[assignment]
    out = tool.run(context=_ctx(store), action="lookup_profile", username="ada")
    assert out.metadata["error"] == "rate_limited"
    assert out.metadata["status"] == 429
    assert out.metadata["retry_after"] == 30


def test_http_error_surfaces_status_and_message():
    store = _store_bearer()
    tool = LinkedInSearchTool(credential_store=store)

    def raise_404(**_kwargs):
        raise _http_error(404, body=b'{"message":"Profile not found"}')

    tool._request_json = raise_404  # type: ignore[assignment]
    out = tool.run(context=_ctx(store), action="lookup_profile", username="nobody")
    assert out.metadata["error"] == "http_error"
    assert out.metadata["status"] == 404
    assert out.metadata["message"] == "Profile not found"
    assert "404" in out.text


# reference import so lint keeps it
assert pytest is not None
