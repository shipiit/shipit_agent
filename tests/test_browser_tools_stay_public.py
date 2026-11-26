"""The browser tools cannot be pointed at this machine, its network or its files.

Playwright is faked, so nothing is launched and nothing leaves the machine;
DNS is faked so public.test is a public address and internal.test is loopback.
"""

from __future__ import annotations

import socket
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import pytest

from shipit_agent.computer_use.browser_session import PlaywrightBrowserSession
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.open_url.safe_fetch import guard_browser_context
from shipit_agent.tools.open_url.url_safety import URLNotAllowedError
from shipit_agent.tools.playwright_browser.playwright_browser_tool import PlaywrightBrowserTool

INTERNAL = ["http://127.0.0.1:8080/admin", "http://169.254.169.254/latest/meta-data/", "http://internal.test/",
            "file:///etc/passwd", "chrome://settings"]


class _Page:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log
        self.url = "about:blank"

    def goto(self, url: str, **_: Any) -> None:
        self.log["visited"].append(url)
        self.url = self.log.get("lands_on") or url

    def content(self) -> str:
        return "<html><body>PAGE BODY</body></html>"

    def wait_for_timeout(self, _: int) -> None:
        pass


class _Context:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log

    def route(self, pattern: str, handler: Any) -> None:
        self.log["routes"].append((pattern, handler))

    def new_page(self) -> _Page:
        return _Page(self.log)


class _Browser:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log

    def new_context(self, **_: Any) -> _Context:
        return _Context(self.log)

    def new_page(self) -> _Page:  # an unguarded page: the tools must not use it
        self.log["unguarded_pages"] += 1
        return _Page(self.log)

    def close(self) -> None:
        pass


class _Playwright:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log
        self.chromium = types.SimpleNamespace(launch=self._launch)

    def _launch(self, **_: Any) -> _Browser:
        self.log["launches"] += 1
        return _Browser(self.log)

    def start(self) -> "_Playwright":
        return self

    def stop(self) -> None:
        pass

    def __enter__(self) -> "_Playwright":
        return self

    def __exit__(self, *_: object) -> None:
        pass


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    log: dict[str, Any] = {"launches": 0, "routes": [], "visited": [], "unguarded_pages": 0}
    module = types.ModuleType("playwright.sync_api")
    setattr(module, "sync_playwright", lambda: _Playwright(log))
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    real = socket.getaddrinfo

    def fake_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        answer = {"public.test": "93.184.216.34", "internal.test": "127.0.0.1"}.get(host)
        if answer is None:
            return real(host, port, *args, **kwargs)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (answer, int(port or 80)))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    yield log


CTX = ToolContext(prompt="")


@pytest.mark.parametrize("url", INTERNAL)
def test_playwright_browse_refuses_internal_urls_before_launching(browser: dict[str, Any], url: str) -> None:
    out = PlaywrightBrowserTool().run(CTX, url=url)
    assert out.metadata["blocked"] is True and "PAGE BODY" not in out.text
    assert browser["launches"] == 0


def test_playwright_browse_checks_every_request_of_a_public_page(browser: dict[str, Any]) -> None:
    out = PlaywrightBrowserTool().run(CTX, url="http://public.test/page")
    assert "PAGE BODY" in out.text
    assert browser["visited"] == ["http://public.test/page"]
    assert len(browser["routes"]) == 1 and browser["unguarded_pages"] == 0


def test_playwright_browse_refuses_a_page_that_ends_on_an_internal_address(browser: dict[str, Any]) -> None:
    browser["lands_on"] = "http://127.0.0.1:8080/admin"
    out = PlaywrightBrowserTool().run(CTX, url="http://public.test/redirect")
    assert "PAGE BODY" not in out.text and out.metadata.get("error")


def test_playwright_browse_allow_private_hosts_turns_the_checks_off(browser: dict[str, Any]) -> None:
    out = PlaywrightBrowserTool(allow_private_hosts=True).run(CTX, url="http://127.0.0.1:8080/admin")
    assert "PAGE BODY" in out.text and browser["routes"] == []


def test_the_context_guard_aborts_internal_requests_and_lets_public_ones_through(browser: dict[str, Any]) -> None:
    guard_browser_context(_Context(browser))
    (pattern, handler), = browser["routes"]
    assert pattern == "**/*"
    seen: list[str] = []

    def route(url: str) -> Any:
        return types.SimpleNamespace(request=types.SimpleNamespace(url=url), continue_=lambda: seen.append("continue"),
                                     abort=lambda reason: seen.append(f"abort:{reason}"))

    for url in ("http://public.test/app.js", "http://internal.test/secret", "data:text/plain,hi"):
        handler(route(url))
    assert seen == ["continue", "abort:blockedbyclient", "continue"]


def _session(log: dict[str, Any], *, allow_private_hosts: bool = False) -> PlaywrightBrowserSession:
    session = PlaywrightBrowserSession(executor=ThreadPoolExecutor(max_workers=1), browser=_Browser(log),
                                       page=_Page(log), playwright=_Playwright(log), viewport_size=(800, 600))
    session._allow_private_hosts = allow_private_hosts
    return session


@pytest.mark.parametrize("url", INTERNAL)
def test_the_computer_use_browser_refuses_to_navigate_inside(browser: dict[str, Any], url: str) -> None:
    with pytest.raises(URLNotAllowedError):
        _session(browser).navigate(url)
    assert browser["visited"] == []


def test_the_computer_use_browser_navigates_to_public_pages(browser: dict[str, Any]) -> None:
    _session(browser).navigate("http://public.test/")
    _session(browser, allow_private_hosts=True).navigate("http://127.0.0.1:3000/")
    assert browser["visited"] == ["http://public.test/", "http://127.0.0.1:3000/"]


@pytest.mark.parametrize(("allow", "routes"), [(False, 1), (True, 0)])
def test_launching_the_computer_use_browser_guards_its_context(browser: dict[str, Any], allow: bool, routes: int) -> None:
    session = PlaywrightBrowserSession.launch(settle_ms=0, allow_private_hosts=allow)
    assert len(browser["routes"]) == routes
    assert browser["visited"] == ["about:blank"]  # the operator's own start page is not checked
    session._executor.shutdown(wait=False)
