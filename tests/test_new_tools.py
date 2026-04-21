"""Tests for the new persona tools (computer_use, hubspot, research_brief).

These tests never hit a real desktop or real API — mocks/stubs verify the
tool's behavior without external dependencies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.computer_use import ComputerUseTool, TAKE_SCREENSHOT_ACTIONS
from shipit_agent.tools.hubspot import HubspotTool
from shipit_agent.tools.research_brief import ResearchBriefTool


# ─────────────────────── computer_use ───────────────────────


class _FakeBackend:
    """Captures calls instead of actually driving the desktop."""

    def __init__(self, *, fail_screenshot: bool = False) -> None:
        self.platform = "test"
        self.calls: list[tuple[str, tuple, dict]] = []
        self.fail_screenshot = fail_screenshot

    def screenshot(self, path: Path) -> Path:
        if self.fail_screenshot:
            from shipit_agent.tools.computer_use.backends import BackendError
            raise BackendError("backend missing")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        self.calls.append(("screenshot", (path,), {}))
        return path

    def move(self, x: int, y: int) -> None: self.calls.append(("move", (x, y), {}))
    def click(self, x: int, y: int, **kw: Any) -> None: self.calls.append(("click", (x, y), kw))
    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        self.calls.append(("drag", (x, y, to_x, to_y), {}))
    def type_text(self, text: str) -> None: self.calls.append(("type_text", (text,), {}))
    def key(self, keys: str) -> None: self.calls.append(("key", (keys,), {}))
    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.calls.append(("scroll", (x, y, dx, dy), {}))


@pytest.fixture
def fake_backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(
        "shipit_agent.tools.computer_use.computer_use_tool.resolve_backend",
        lambda: fake,
    )
    return fake


class TestComputerUseTool:
    def _ctx(self) -> ToolContext: return ToolContext(prompt="test")

    def test_schema_has_all_actions(self) -> None:
        tool = ComputerUseTool()
        actions = tool.schema()["function"]["parameters"]["properties"]["action"]["enum"]
        for a in ["screenshot", "click", "mouse_move", "type", "key", "scroll", "drag", "wait"]:
            assert a in actions

    def test_rejects_unknown_action(self, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="dance")
        assert "unsupported action" in out.text
        assert out.metadata["ok"] is False

    def test_screenshot_writes_file(self, fake_backend: _FakeBackend, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="screenshot")
        assert out.metadata["ok"] is True
        path = Path(out.metadata["path"])
        assert path.exists() and path.read_bytes() == b"fake-png"

    def test_click_delegates_to_backend(self, fake_backend: _FakeBackend, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="click", x=100, y=200, button="right", double=True)
        assert out.metadata["ok"] is True
        assert fake_backend.calls[-1][0] == "click"
        assert fake_backend.calls[-1][2] == {"button": "right", "double": True}

    def test_missing_xy_errors_cleanly(self, fake_backend: _FakeBackend, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="click")  # no x/y
        assert out.metadata["ok"] is False
        assert "x" in out.text and "y" in out.text

    def test_type_requires_text(self, fake_backend: _FakeBackend, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="type")
        assert out.metadata["ok"] is False
        assert "text" in out.text

    def test_wait_does_not_call_backend(self, fake_backend: _FakeBackend, tmp_path: Path) -> None:
        tool = ComputerUseTool(output_dir=tmp_path)
        tool.run(self._ctx(), action="wait", seconds=0.01)
        assert not fake_backend.calls

    def test_backend_error_surfaces_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "shipit_agent.tools.computer_use.computer_use_tool.resolve_backend",
            lambda: _FakeBackend(fail_screenshot=True),
        )
        tool = ComputerUseTool(output_dir=tmp_path)
        out = tool.run(self._ctx(), action="screenshot")
        assert out.metadata["ok"] is False
        assert "backend missing" in out.text


# ─────────────────────── hubspot ───────────────────────


class _MockHTTPResp:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode("utf-8")
    def __enter__(self) -> "_MockHTTPResp": return self
    def __exit__(self, *a: Any) -> None: pass
    def read(self, _n: int = -1) -> bytes: return self._body


class TestHubspotTool:
    def _ctx(self) -> ToolContext: return ToolContext(prompt="test")

    def test_missing_token_fails_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
        tool = HubspotTool(token=None)
        out = tool.run(self._ctx(), action="search_contacts", query="x")
        assert out.metadata["ok"] is False
        assert "HUBSPOT_TOKEN" in out.text

    def test_search_contacts_formats_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responses = iter([
            _MockHTTPResp({"results": [
                {"id": "1", "properties": {"email": "a@x.com", "firstname": "A", "lastname": "B"}},
                {"id": "2", "properties": {"email": "c@y.com", "firstname": "C", "lastname": "D"}},
            ]})
        ])
        monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: next(responses))
        tool = HubspotTool(token="fake")
        out = tool.run(self._ctx(), action="search_contacts", query="a")
        assert out.metadata["ok"] is True
        assert "a@x.com" in out.text
        assert "c@y.com" in out.text

    def test_create_contact_without_properties_errors(self) -> None:
        tool = HubspotTool(token="fake")
        out = tool.run(self._ctx(), action="create_contact")
        assert out.metadata["ok"] is False
        assert "properties" in out.text

    def test_unknown_action(self) -> None:
        tool = HubspotTool(token="fake")
        out = tool.run(self._ctx(), action="bogus")
        assert out.metadata["ok"] is False


# ─────────────────────── research_brief ───────────────────────


class TestResearchBriefTool:
    def _ctx(self) -> ToolContext: return ToolContext(prompt="test")

    def test_empty_query_errors(self) -> None:
        tool = ResearchBriefTool()
        out = tool.run(self._ctx(), query="")
        assert out.metadata["ok"] is False

    def test_formats_brief_with_fake_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_html = (
            '<a rel="nofollow" class="result__a" href="https://a.com">Alpha site</a>'
            '<a class="result__snippet" href="">alpha snippet text</a>'
            '<a rel="nofollow" class="result__a" href="https://b.com">Beta site</a>'
            '<a class="result__snippet" href="">beta snippet</a>'
        )
        tool = ResearchBriefTool()
        monkeypatch.setattr(tool, "_fetch", lambda _u: fake_html)
        out = tool.run(self._ctx(), query="example", max_sources=2)
        assert out.metadata["ok"] is True
        assert "Alpha site" in out.text
        assert "https://a.com" in out.text
        assert "[1]" in out.text and "[2]" in out.text

    def test_tolerates_no_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tool = ResearchBriefTool()
        monkeypatch.setattr(tool, "_fetch", lambda _u: "<html>no results</html>")
        out = tool.run(self._ctx(), query="nothing", max_sources=3)
        assert out.metadata["ok"] is True
        assert "no sources found" in out.text

    def test_net_error_surfaces_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tool = ResearchBriefTool()
        def _boom(_u: str) -> str:
            from shipit_agent.tools.research_brief.research_brief_tool import _NetError
            raise _NetError("DNS failure")
        monkeypatch.setattr(tool, "_fetch", _boom)
        out = tool.run(self._ctx(), query="x")
        assert out.metadata["ok"] is False
        assert "DNS failure" in out.text
