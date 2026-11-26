"""Model-chosen URLs cannot reach this machine or its network: not directly, by redirect, or by DNS rebinding.

Two throwaway servers on 127.0.0.1 play an "internal" service and a "public"
site. DNS is faked inside the test: public.test resolves to a documentation
address that is routed to the public server, internal.test to 127.0.0.1, and
rebind.test to the public address for its first two lookups (the checks) and
to 127.0.0.1 after (the moment a connection would look it up again). Nothing leaves
the machine.
"""

from __future__ import annotations

import http.server
import socket
import threading
import urllib.request
from typing import Any, Iterator

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.download_file.download_file_tool import DownloadFileTool
from shipit_agent.tools.fetch_url.fetch_url_tool import FetchUrlTool
from shipit_agent.tools.open_url import safe_fetch
from shipit_agent.tools.open_url.open_url_tool import OpenURLTool
from shipit_agent.tools.open_url.safe_fetch import safe_urlopen
from shipit_agent.tools.open_url.url_safety import URLNotAllowedError

PUBLIC_IP = "93.184.216.34"  # never contacted: connections to it are routed to the local "public" server


def _server(body: bytes, redirect_to: str | None = None) -> http.server.HTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if redirect_to is not None and self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", redirect_to)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    internal = _server(b"INTERNAL-SECRET")
    ip_port = internal.server_address[1]
    public = _server(b"PUBLIC-PAGE", redirect_to=f"http://internal.test:{ip_port}/latest/meta-data/")
    pub_port = public.server_address[1]
    lookups: dict[str, int] = {}
    real_getaddrinfo, real_connect = socket.getaddrinfo, socket.create_connection

    def fake_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        lookups[host] = lookups.get(host, 0) + 1
        answer = {"public.test": PUBLIC_IP, "internal.test": "127.0.0.1",
                  "rebind.test": PUBLIC_IP if lookups[host] <= 2 else "127.0.0.1"}.get(host)
        if answer is None:
            return real_getaddrinfo(host, port, *args, **kwargs)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (answer, int(port or 80)))]

    def fake_connect(address: Any, *args: Any, **kwargs: Any) -> Any:
        if address[0] == PUBLIC_IP:
            return real_connect(("127.0.0.1", pub_port), *args, **kwargs)
        return real_connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_connect)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    yield {"public": f"http://public.test:{pub_port}", "internal": f"http://internal.test:{ip_port}",
           "rebind": f"http://rebind.test:{ip_port}", "lookups": lookups}
    internal.shutdown()
    public.shutdown()


def _read(url: str) -> str:
    with safe_urlopen(url, timeout=5) as response:
        return response.read().decode()


def test_a_public_page_is_fetched(net: dict[str, Any]) -> None:
    assert _read(net["public"] + "/page") == "PUBLIC-PAGE"


def test_an_internal_address_is_refused(net: dict[str, Any]) -> None:
    with pytest.raises(URLNotAllowedError):
        _read(net["internal"] + "/latest/meta-data/")


def test_a_redirect_to_an_internal_address_is_refused(net: dict[str, Any]) -> None:
    with pytest.raises(URLNotAllowedError):
        _read(net["public"] + "/redirect")


def test_dns_rebinding_cannot_swap_the_address_after_the_check(net: dict[str, Any]) -> None:
    # The name is public when checked and internal when looked up again; the
    # connection goes to the checked address, so the internal secret is never read.
    assert _read(net["rebind"] + "/latest/meta-data/") == "PUBLIC-PAGE"
    assert net["lookups"]["rebind.test"] == 2  # checked twice, never looked up to connect
    # Plain urllib looks the name up again to connect: that lookup is the hazard this closes.
    net["lookups"]["rebind.test"] = 2
    with urllib.request.urlopen(net["rebind"] + "/latest/meta-data/", timeout=5) as response:
        assert response.read() == b"INTERNAL-SECRET"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://public.test/x", "gopher://x/", "http:///nohost"])
def test_other_schemes_and_hostless_urls_are_refused(net: dict[str, Any], url: str) -> None:
    with pytest.raises(URLNotAllowedError):
        _read(url)


def test_allow_private_turns_the_check_off(net: dict[str, Any]) -> None:
    with safe_urlopen(net["internal"] + "/", timeout=5, allow_private=True) as response:
        assert response.read() == b"INTERNAL-SECRET"


def test_too_many_redirects_stop(net: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_fetch, "MAX_REDIRECTS", 0)
    monkeypatch.setattr(safe_fetch._LimitedRedirects, "max_redirections", 0)
    with pytest.raises(Exception):
        _read(net["public"] + "/redirect")


CTX = ToolContext(prompt="")


def test_fetch_url_refuses_internal_and_redirected_addresses(net: dict[str, Any]) -> None:
    tool = FetchUrlTool()
    for url in (net["internal"] + "/", net["public"] + "/redirect", net["rebind"] + "/"):
        out = tool.run(CTX, url=url)
        assert "INTERNAL-SECRET" not in str(getattr(out, "text", out))
    assert "PUBLIC-PAGE" in str(getattr(tool.run(CTX, url=net["public"] + "/"), "text", ""))


def test_open_url_refuses_a_redirect_into_the_network(net: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    tool = OpenURLTool()
    monkeypatch.setattr(tool, "_fetch_via_playwright", lambda url: (_ for _ in ()).throw(ImportError()))
    out = tool.run(CTX, url=net["public"] + "/redirect")
    assert "INTERNAL-SECRET" not in out.text and "error" in out.metadata


def test_download_file_refuses_a_redirect_into_the_network(net: dict[str, Any], tmp_path: Any) -> None:
    out = DownloadFileTool(workspace_root=tmp_path).run(CTX, url=net["public"] + "/redirect")
    assert out.metadata["ok"] is False
    assert not any(p.read_bytes() == b"INTERNAL-SECRET" for p in tmp_path.rglob("*") if p.is_file())


def test_research_brief_refuses_internal_results(net: dict[str, Any]) -> None:
    from shipit_agent.tools.research_brief.research_brief_tool import ResearchBriefTool, _NetError

    with pytest.raises(_NetError):
        ResearchBriefTool()._fetch(net["public"] + "/redirect")


def test_the_browser_route_aborts_internal_requests() -> None:
    from shipit_agent.tools.open_url.browser_fetch import _guard_route

    calls: list[str] = []

    class Route:
        def __init__(self, url: str) -> None:
            self.request = type("R", (), {"url": url})()

        def continue_(self) -> None:
            calls.append("continue")

        def abort(self, reason: str) -> None:
            calls.append(f"abort:{reason}")

    for url in ("http://127.0.0.1:8080/", "http://169.254.169.254/latest/", "data:text/plain,hi", "file:///etc/passwd"):
        _guard_route(Route(url))
    assert calls == ["abort:blockedbyclient", "abort:blockedbyclient", "continue", "abort:blockedbyclient"]
