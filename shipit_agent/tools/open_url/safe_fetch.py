"""Fetching a URL a model chose, without reaching this machine or its network.

Every request, redirects included, goes through :func:`checked_address`: the
host is resolved, every address it maps to must be public, and the connection
is made to exactly the address that was checked. So a redirect to
``169.254.169.254`` is refused, and so is a name that resolves to a public
address when checked and to an internal one a moment later (DNS rebinding).
Only http and https are handled; there is no file, ftp or data handler.

Through a proxy the proxy does the resolving, so only the check applies.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from .url_safety import URLNotAllowedError, _ip_is_blocked

__all__ = ["checked_address", "guard_browser_context", "guard_browser_route", "safe_urlopen"]

MAX_REDIRECTS = 5


def checked_address(url: str) -> str:
    """The public address *url*'s host resolves to; raises ``URLNotAllowedError`` otherwise."""
    parts = urlsplit(url)
    if (parts.scheme or "").lower() not in ("http", "https"):
        raise URLNotAllowedError(f"Only http/https URLs are allowed (got scheme '{parts.scheme or 'none'}')")
    host = parts.hostname
    if not host:
        raise URLNotAllowedError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise URLNotAllowedError(f"Could not resolve host '{host}': {exc}") from exc
    addresses = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise URLNotAllowedError(
                f"Host '{host}' resolves to a blocked address ({ip}); "
                "private/loopback/link-local/reserved hosts are not allowed"
            )
        addresses.append(str(ip))
    if not addresses:
        raise URLNotAllowedError(f"Host '{host}' has no usable address")
    return addresses[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, pinned: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pinned = pinned

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, pinned: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pinned = pinned

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned, self.port), self.timeout, self.source_address)
        # The certificate is still checked against the real host name.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        if req.has_proxy():
            checked_address(req.full_url)
            return super().http_open(req)
        pinned = checked_address(req.full_url)
        return self.do_open(lambda host, **kw: _PinnedHTTPConnection(host, pinned=pinned, **kw), req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        if req.has_proxy():
            checked_address(req.full_url)
            return super().https_open(req)
        pinned = checked_address(req.full_url)
        return self.do_open(lambda host, **kw: _PinnedHTTPSConnection(host, pinned=pinned, **kw), req,
                            context=self._context)


class _LimitedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if (urlsplit(newurl).scheme or "").lower() not in ("http", "https"):
            raise URLNotAllowedError(f"Refusing a redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(request: urllib.request.Request | str, *, timeout: float, allow_private: bool = False) -> Any:
    """``urlopen`` for model-chosen URLs. ``allow_private`` turns the checks off for trusted internal use."""
    if allow_private:
        return urllib.request.urlopen(request, timeout=timeout)  # nosec B310 — the caller opted out
    # Checked before anything opens: another scheme or a missing host is refused here,
    # not left to fall through the handlers.
    checked_address(request.full_url if isinstance(request, urllib.request.Request) else str(request))
    opener = urllib.request.OpenerDirector()
    proxies = urllib.request.getproxies()
    handlers: list[Any] = [
        urllib.request.ProxyHandler({k: v for k, v in proxies.items() if k in ("http", "https", "no")}),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(),
        _LimitedRedirects(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ]
    for handler in handlers:
        opener.add_handler(handler)
    return opener.open(request, timeout=timeout)


def guard_browser_route(route: Any) -> None:
    """A browser request goes ahead only to a public http(s) address; data and blob URLs stay local."""
    url = str(route.request.url)
    if url.startswith(("data:", "blob:")):
        route.continue_()
        return
    try:
        checked_address(url)
    except URLNotAllowedError:
        route.abort("blockedbyclient")
        return
    route.continue_()


def guard_browser_context(context: Any) -> None:
    """Check every request a Playwright browser context makes: page loads, redirects, scripts' fetches."""
    context.route("**/*", guard_browser_route)
