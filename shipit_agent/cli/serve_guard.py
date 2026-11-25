"""Which requests `shipit serve` accepts.

The served agent has real tools, and a web page open in the developer's browser
can reach 127.0.0.1. Three checks keep pages out:

* a POST must be ``application/json``: a page can send ``text/plain`` without a
  CORS preflight, but not JSON;
* a request that names a browser ``Origin`` must name an allowed one;
* on a loopback address the ``Host`` must be a loopback name, which stops a
  DNS-rebinding page that points its own domain at 127.0.0.1.

Bound anywhere else the server always needs a key; one is generated if none
was given.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
from typing import Any

__all__ = ["is_loopback", "key_matches", "new_key", "request_problem"]

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "ip6-localhost"})


def is_loopback(host: str) -> bool:
    """Whether *host* (a bind address or a Host header's name) is this machine only."""
    name = host.strip().strip("[]").lower()
    if name in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def new_key() -> str:
    return secrets.token_urlsafe(32)


def key_matches(header: str, key: str) -> bool:
    """A Bearer header against the key, in constant time."""
    return hmac.compare_digest(header.encode(), f"Bearer {key}".encode())


def _host_name(header: str) -> str:
    header = header.strip()
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def request_problem(
    headers: Any, *, post: bool, bound_host: str, allowed_origins: frozenset[str]
) -> tuple[int, str] | None:
    """``(status, message)`` for a request to refuse, or ``None`` to serve it."""
    if is_loopback(bound_host) and not is_loopback(_host_name(headers.get("Host", ""))):
        return 421, "This server answers only to localhost."
    origin = headers.get("Origin")
    if origin and origin.rstrip("/") not in allowed_origins:
        return 403, f"Origin {origin} is not allowed; start the server with allowed_origins to permit it."
    if post and not headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json":
        return 415, "Send the request body as application/json."
    return None
