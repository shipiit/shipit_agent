"""Tests for DownloadFileTool — binary-safe URL downloads with guards."""

from __future__ import annotations

import http.server
import threading

import pytest

from shipit_agent.tools import DownloadFileTool
from shipit_agent.tools.base import ToolContext

CTX = ToolContext(prompt="", system_prompt="", state={})
PAYLOAD = b"\x89PNG fake-binary-content " * 100  # 2,500 bytes, non-UTF8


@pytest.fixture()
def http_server(tmp_path):
    """Local HTTP server serving a small binary payload."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAYLOAD
            self.send_response(200)
            if self.path.endswith("named"):
                self.send_header(
                    "Content-Disposition", 'attachment; filename="report Q2.zip"'
                )
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _tool(tmp_path, **kwargs) -> DownloadFileTool:
    # local server → allow loopback for the test
    return DownloadFileTool(
        workspace_root=tmp_path, allow_private_hosts=True, **kwargs
    )


class TestDownload:
    def test_downloads_binary_to_workspace(self, tmp_path, http_server) -> None:
        out = _tool(tmp_path).run(CTX, url=f"{http_server}/data.bin")
        assert out.metadata["ok"] is True
        assert out.metadata["bytes"] == len(PAYLOAD)
        with open(out.metadata["path"], "rb") as fh:
            assert fh.read() == PAYLOAD
        assert out.metadata["path"].endswith("data.bin")

    def test_content_disposition_filename(self, tmp_path, http_server) -> None:
        out = _tool(tmp_path).run(CTX, url=f"{http_server}/named")
        assert out.metadata["path"].endswith("report Q2.zip")

    def test_explicit_path(self, tmp_path, http_server) -> None:
        out = _tool(tmp_path).run(
            CTX, url=f"{http_server}/x", path="sub/dir/archive.bin"
        )
        assert out.metadata["ok"] is True
        assert out.metadata["path"].endswith("sub/dir/archive.bin")

    def test_no_overwrite_by_default(self, tmp_path, http_server) -> None:
        tool = _tool(tmp_path)
        first = tool.run(CTX, url=f"{http_server}/data.bin")
        assert first.metadata["ok"]
        second = tool.run(CTX, url=f"{http_server}/data.bin")
        assert second.metadata["ok"] is False
        assert second.metadata["error"] == "exists"
        third = tool.run(CTX, url=f"{http_server}/data.bin", overwrite=True)
        assert third.metadata["ok"] is True


class TestGuards:
    def test_size_cap_aborts_and_removes_partial(self, tmp_path, http_server) -> None:
        out = _tool(tmp_path, max_bytes=100).run(CTX, url=f"{http_server}/big.bin")
        assert out.metadata["ok"] is False
        assert not (tmp_path / "big.bin").exists()  # no partial file left

    def test_file_scheme_blocked(self, tmp_path) -> None:
        tool = DownloadFileTool(workspace_root=tmp_path)  # guard ON
        out = tool.run(CTX, url="file:///etc/passwd")
        assert out.metadata["ok"] is False
        assert out.metadata["error"] == "url_not_allowed"

    def test_loopback_blocked_when_guard_on(self, tmp_path) -> None:
        tool = DownloadFileTool(workspace_root=tmp_path)
        out = tool.run(CTX, url="http://127.0.0.1:9/x")
        assert out.metadata["ok"] is False
        assert out.metadata["error"] == "url_not_allowed"

    def test_missing_url(self, tmp_path) -> None:
        out = _tool(tmp_path).run(CTX)
        assert out.metadata["ok"] is False

    def test_in_builtin_catalogue(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = [t.name for t in get_builtin_tools(project_root=".")]
        assert "download_file" in names
