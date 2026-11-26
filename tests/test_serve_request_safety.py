"""`shipit serve` refuses requests a web page could send, and never runs keyless off this machine.

The server runs an agent with real tools. A page open in the developer's browser
can reach 127.0.0.1; it must not be able to start a run (a text/plain POST needs
no CORS preflight) or read one (a DNS-rebinding page sends its own Host).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.cli.serve import AgentServer, is_loopback
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse

RAN: list[str] = []


def _marker(note: str = "") -> str:
    """Record that a tool ran."""
    RAN.append(note)
    return "ok"


class _Model:
    model = "m"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn % 2 == 1:
            return LLMResponse(tool_calls=[ToolCall(name="marker", arguments={"note": "x"}, id=f"c{self.turn}")])
        return LLMResponse(content="done")


@pytest.fixture
def served(request: pytest.FixtureRequest) -> Any:
    RAN.clear()
    options = getattr(request, "param", {})
    server = AgentServer(Agent(llm=_Model(), tools=[FunctionTool.from_callable(_marker, name="marker")]), **options)
    port = server.start(port=0)
    yield port, server
    server.stop()


CHAT = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}


def _send(port: int, path: str = "/v1/chat/completions", *, body: Any = CHAT, method: str = "POST", **headers: str) -> int:
    data = json.dumps(body).encode() if method == "POST" else None
    sent = {"Content-Type": "application/json", **{k.replace("_", "-"): v for k, v in headers.items()}}
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=sent, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_a_plain_json_request_from_this_machine_works(served: Any) -> None:
    port, _ = served
    assert _send(port) == 200 and RAN == ["x"]


def test_a_text_plain_post_that_needs_no_preflight_is_refused_before_any_run(served: Any) -> None:
    port, _ = served
    for path in ("/v1/chat/completions", "/v1/stream"):
        assert _send(port, path, Content_Type="text/plain;charset=UTF-8", body={**CHAT, "prompt": "hi"}) == 415
    assert RAN == []


def test_a_browser_origin_that_is_not_allowed_is_refused(served: Any) -> None:
    port, _ = served
    assert _send(port, Origin="https://evil.example") == 403
    assert _send(port, "/v1/models", method="GET", Origin="https://evil.example") == 403
    assert RAN == []


@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8399", "127.0.0.1.attacker.example"])
def test_a_foreign_host_header_is_refused_on_every_route(served: Any, host: str) -> None:
    port, _ = served
    assert _send(port, Host=host) == 421
    assert _send(port, "/v1/models", method="GET", Host=host) == 421
    assert _send(port, "/health", method="GET", Host=host) == 421
    assert RAN == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_host_names_are_accepted(served: Any, host: str) -> None:
    port, _ = served
    assert _send(port, Host=f"{host}:{port}") == 200


@pytest.mark.parametrize("served", [{"allowed_origins": ["http://localhost:3000"]}], indirect=True)
def test_an_allowed_origin_may_call(served: Any) -> None:
    port, _ = served
    assert _send(port, Origin="http://localhost:3000") == 200
    assert _send(port, Origin="http://localhost:3001") == 403


@pytest.mark.parametrize("served", [{"api_key": "sekrit"}], indirect=True)
def test_the_key_is_still_required(served: Any) -> None:
    port, _ = served
    assert _send(port) == 401
    assert _send(port, Authorization="Bearer wrong") == 401
    assert _send(port, Authorization="Bearer sekrit") == 200


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "example.internal"])
def test_off_this_machine_the_server_refuses_to_start_without_a_key(host: str) -> None:
    server = AgentServer(Agent(llm=_Model()))
    with pytest.raises(ValueError, match="--api-key"):
        server.start(host=host, port=0)
    assert server.api_key is None  # none is invented: a key nobody was shown locks everyone out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_on_this_machine_no_key_is_needed(host: str) -> None:
    server = AgentServer(Agent(llm=_Model()))
    server.require_key_for(host)
    assert server.api_key is None


def test_a_given_key_is_kept_off_this_machine() -> None:
    keyed = AgentServer(Agent(llm=_Model()), api_key="mine")
    keyed.require_key_for("0.0.0.0")
    assert keyed.api_key == "mine"


def test_shipit_serve_exits_with_the_reason_and_prints_no_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from shipit_agent.cli.commands import serve_cmd

    monkeypatch.setattr(serve_cmd, "build_agent", lambda args: Agent(llm=_Model()))
    served: list[str] = []
    monkeypatch.setattr(AgentServer, "serve_forever", lambda self, **kw: served.append(kw["host"]))
    args = argparse.Namespace(name="shipit", api_key=None, allow_origin="", host="0.0.0.0", port=8399)
    assert serve_cmd.cmd_serve(args) == 2
    output = capsys.readouterr()
    assert served == [] and "--api-key" in output.out + output.err

    args.api_key = "sekrit-value-123"
    assert serve_cmd.cmd_serve(args) == 0
    output = capsys.readouterr()
    assert served == ["0.0.0.0"] and "sekrit-value-123" not in output.out + output.err


@pytest.mark.parametrize(("host", "expected"), [
    ("127.0.0.1", True), ("localhost", True), ("::1", True), ("127.5.5.5", True),
    ("0.0.0.0", False), ("192.168.1.5", False), ("example.com", False), ("", False),
])
def test_is_loopback(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected
