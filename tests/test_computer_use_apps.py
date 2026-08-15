"""computer_use app/window control — list_apps and focus_app.

Backend-mocked so the test runs on any platform (the live osascript path is
macOS-only). Verifies the tool wires the new actions to the backend and shapes
the result the model reads.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.computer_use import computer_use_tool as cut
from shipit_agent.tools.computer_use.computer_use_tool import ComputerUseTool


class FakeBackend:
    platform = "test"

    def __init__(self):
        self.focused = None

    def list_apps(self):
        return ["Safari", "Terminal", "Finder"]

    def focus_app(self, name):
        self.focused = name


@pytest.fixture
def tool(monkeypatch, tmp_path):
    backend = FakeBackend()
    monkeypatch.setattr(cut, "resolve_backend", lambda: backend)
    t = ComputerUseTool(output_dir=tmp_path)
    t._backend = backend  # expose for assertions
    return t


def _ctx():
    return ToolContext(prompt="")


def test_new_actions_are_in_the_schema():
    enum = ComputerUseTool().schema()["function"]["parameters"]["properties"]["action"]["enum"]
    assert "list_apps" in enum and "focus_app" in enum


def test_list_apps_returns_the_running_apps(tool):
    out = tool.run(_ctx(), action="list_apps")
    assert out.metadata["ok"] is True
    assert out.metadata["apps"] == ["Safari", "Terminal", "Finder"]
    assert "Safari" in out.text


def test_focus_app_activates_the_named_app(tool):
    out = tool.run(_ctx(), action="focus_app", app="Safari")
    assert out.metadata["ok"] is True
    assert tool._backend.focused == "Safari"


def test_focus_app_accepts_text_as_alias(tool):
    tool.run(_ctx(), action="focus_app", text="Terminal")
    assert tool._backend.focused == "Terminal"


def test_focus_app_without_a_name_is_an_error(tool):
    out = tool.run(_ctx(), action="focus_app")
    assert out.metadata["ok"] is False
    assert "required" in out.text
