"""Which addresses open_url refuses: loopback, private, link-local and the like."""

from __future__ import annotations

import ipaddress


class URLNotAllowedError(ValueError):
    """Raised when a requested URL fails the SSRF / scheme guard."""


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ``ip`` is a private/loopback/link-local/reserved address.

    169.254.0.0/16 (and the IPv6 link-local equivalent) is the cloud-metadata
    range; ``is_link_local`` already covers it but we keep the explicit check
    for clarity and defence in depth.
    """
    link_local_v4 = ipaddress.ip_network("169.254.0.0/16")
    if isinstance(ip, ipaddress.IPv4Address) and ip in link_local_v4:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# A realistic desktop Chrome UA — many sites 503/403 minimal clients.
