"""``shipit sdk``: one prompt through the SDK layer, drawn live or as JSON lines."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from shipit_agent.cli import main
from shipit_agent.cli.commands import sdk_cmd
from shipit_agent.cli.sdk_render import LiveRenderer
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolResultBlock,
    UserMessage,
)

USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cache_read_input_tokens": 80}


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, text_delta_callback: Any = None, tool_input_callback: Any = None, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            if tool_input_callback is not None:
                for piece in ('{"pa', 'th": "README.md"}'):
                    tool_input_callback("c1", "read_file", piece)
            return LLMResponse(content="", tool_calls=[ToolCall(name="read_file", arguments={"path": "README.md"}, id="c1")], usage=USAGE)
        for chunk in ("All ", "good."):
            if text_delta_callback is not None:
                text_delta_callback(chunk)
        return LLMResponse(content="All good.", usage=USAGE)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    (tmp_path / "README.md").write_text("# Project\n")
    monkeypatch.setattr("shipit_agent.sdk.build.llm_for_model", lambda _model: _Model())
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_live_output_streams_the_tool_call_the_result_and_a_summary(fake_model: Any, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["sdk", "Read the readme", "--tools", "Read", "--allow", "Read"])
    out = capsys.readouterr().out
    assert code == 0
    assert '⚙ read_file {"path": "README.md"}' in out
    assert "✓ " in out and "All good." in out
    assert "✓ done · 2 turns" in out and "read from cache" in out


def test_json_prints_one_message_per_line(fake_model: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sdk", "Read the readme", "--tools", "Read", "--allow", "Read", "--json"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    kinds = [line["type"] for line in lines]
    assert kinds[0] == "SystemMessage" and kinds[-1] == "ResultMessage" and "StreamEvent" not in kinds
    assert lines[-1]["result"] == "All good." and lines[-1]["subtype"] == "success"


def test_a_run_that_stops_short_exits_1(fake_model: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sdk", "Read the readme", "--tools", "Read", "--allow", "Read", "--max-turns", "1"]) == 1
    assert "✗ error_max_turns" in capsys.readouterr().out


def test_options_come_from_the_flags() -> None:
    args = sdk_cmd.parse_args(["hi", "--tools", "Read,Grep", "--allow", "Bash(git commit -m a,b),Read",
                                        "--deny", "Bash(rm *)", "--budget", "0.5", "--cache-ttl", "1h", "--json"])
    options = sdk_cmd.options_from(args)
    assert options.tools == ["Read", "Grep"]
    assert options.allowed_tools == ["Bash(git commit -m a,b)", "Read"]
    assert options.disallowed_tools == ["Bash(rm *)"]
    assert (options.max_budget_usd, options.cache_ttl, options.include_partial_messages) == (0.5, "1h", False)
    assert sdk_cmd.options_from(sdk_cmd.parse_args(["hi"])).tools is None


@pytest.mark.parametrize(("tty", "answer", "allowed"), [(True, "y", True), (True, "", False), (False, "y", False)])
def test_approval_is_asked_on_the_terminal_and_refused_without_one(
    monkeypatch: pytest.MonkeyPatch, tty: bool, answer: str, allowed: bool
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(answer + "\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty, raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)
    result = sdk_cmd._ask_on_terminal("bash", {"command": "rm x"}, None)
    assert isinstance(result, PermissionResultAllow if allowed else PermissionResultDeny)


def test_the_renderer_draws_rate_limits_progress_and_failures() -> None:
    written: list[str] = []
    renderer = LiveRenderer(written.append)
    renderer.feed(RateLimitEvent({"status": "rejected", "resets_at": None}, "u", "s"))
    renderer.feed(SystemMessage("task_progress", {"usage": {"tool_uses": 2, "total_tokens": 1500}}))
    renderer.feed(UserMessage(content=[ToolResultBlock("c1", "disk full", True)]))
    renderer.feed(StreamEvent("u", "s", {"type": "message_start", "message": {}}))
    renderer.feed(ResultMessage("error_during_execution", 1200, 0, True, 1, "s", errors=["ValueError: boom"]))
    text = "".join(written)
    assert "rate limited, retrying" in text and "2 tool calls, 1,500 tokens" in text
    assert "✗ disk full" in text and "✗ error_during_execution" in text and "ValueError: boom" in text
