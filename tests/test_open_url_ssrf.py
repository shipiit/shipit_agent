"""SSRF / local-file-read regression tests for OpenURLTool (SEC-2).

The tool previously fetched any URL: ``file:///etc/passwd`` read local
files and ``http://169.254.169.254/...`` hit cloud metadata. These tests
confirm the scheme + resolved-host guard now blocks those before any fetch
happens, and that the ``allow_private_hosts`` escape hatch works.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.open_url.open_url_tool import (
    OpenURLTool,
    URLNotAllowedError,
    _ip_is_blocked,
)


def _ctx() -> ToolContext:
    return ToolContext(prompt="t", state={})


def _fake_getaddrinfo(ip: str):
    """Build a getaddrinfo stub that always resolves to ``ip``.

    Keeps the SSRF tests deterministic and offline — they exercise our
    classification logic, not live DNS.
    """

    def _resolver(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]

    return _resolver


class TestIpClassification:
    @pytest.mark.parametrize(
        "addr",
        [
            "127.0.0.1",
            "169.254.169.254",  # cloud metadata
            "10.0.0.5",
            "192.168.1.1",
            "172.16.0.1",
            "0.0.0.0",
            "::1",
            "fe80::1",
        ],
    )
    def test_internal_addresses_blocked(self, addr: str) -> None:
        assert _ip_is_blocked(ipaddress.ip_address(addr)) is True

    @pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
    def test_public_addresses_allowed(self, addr: str) -> None:
        assert _ip_is_blocked(ipaddress.ip_address(addr)) is False


class TestValidateUrl:
    def test_file_scheme_rejected(self) -> None:
        tool = OpenURLTool()
        with pytest.raises(URLNotAllowedError):
            tool._validate_url("file:///etc/passwd")

    def test_ftp_scheme_rejected(self) -> None:
        tool = OpenURLTool()
        with pytest.raises(URLNotAllowedError):
            tool._validate_url("ftp://example.com/x")

    def test_metadata_ip_rejected(self) -> None:
        tool = OpenURLTool()
        with pytest.raises(URLNotAllowedError):
            tool._validate_url("http://169.254.169.254/latest/meta-data/")

    def test_loopback_rejected(self) -> None:
        tool = OpenURLTool()
        with pytest.raises(URLNotAllowedError):
            tool._validate_url("http://127.0.0.1:8080/admin")

    def test_localhost_name_rejected(self, monkeypatch) -> None:
        # Deterministic: localhost resolves to loopback.
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
        tool = OpenURLTool()
        with pytest.raises(URLNotAllowedError):
            tool._validate_url("http://localhost/secret")

    def test_public_host_allowed(self, monkeypatch) -> None:
        # Deterministic: pin a public IP so the test doesn't depend on DNS.
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
        tool = OpenURLTool()
        tool._validate_url("https://example.com/")

    def test_allow_private_hosts_bypass(self) -> None:
        tool = OpenURLTool(allow_private_hosts=True)
        # Explicit opt-in: no exception even for loopback / file scheme.
        tool._validate_url("http://127.0.0.1:8080/admin")
        tool._validate_url("file:///etc/passwd")


class TestRunBlocks:
    def test_run_returns_blocked_output_for_file_url(self) -> None:
        tool = OpenURLTool()
        out = tool.run(_ctx(), url="file:///etc/passwd")
        assert out.metadata.get("blocked") is True
        assert "refusing" in out.text.lower()

    def test_run_returns_blocked_output_for_metadata(self) -> None:
        tool = OpenURLTool()
        out = tool.run(_ctx(), url="http://169.254.169.254/latest/meta-data/")
        assert out.metadata.get("blocked") is True
