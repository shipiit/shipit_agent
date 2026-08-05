"""The capability bridge and execute_code — env in a sandbox, secrets outside."""

from __future__ import annotations

import os
import socket

import pytest

from shipit_agent.codemode.bridge import BridgeLimits, BridgeServer
from shipit_agent.codemode.preamble import build_preamble
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.describe_binding.describe_binding_tool import (
    BINDINGS_STATE_KEY,
)
from shipit_agent.tools.execute_code import ExecuteCodeTool
from shipit_agent.tools.execute_code.execute_code_tool import INVOKER_STATE_KEY


class FakeBinding:
    def __init__(self, name, methods):
        self.name = name
        self.methods = {m: None for m in methods}


BINDINGS = {
    "WAREHOUSE": FakeBinding("WAREHOUSE", ["query"]),
    "LINEAR": FakeBinding("LINEAR", ["create_issue", "get_issue"]),
}


def recording_invoker(calls, *, result="ok", fail=False):
    def invoke(binding, method, kwargs):
        calls.append((binding, method, kwargs))
        if fail:
            raise PermissionError("denied by policy")
        return result, {"binding": binding}

    return invoke


def ctx(invoker, bindings=None):
    return ToolContext(
        prompt="x",
        state={
            BINDINGS_STATE_KEY: bindings if bindings is not None else BINDINGS,
            INVOKER_STATE_KEY: invoker,
        },
    )


def run_code(code, invoker=None, calls=None, **tool_kwargs):
    calls = calls if calls is not None else []
    invoker = invoker or recording_invoker(calls)
    tool_kwargs.setdefault("timeout_seconds", 30)
    return ExecuteCodeTool(**tool_kwargs).run(ctx(invoker), code=code)


# ── the bridge on its own ────────────────────────────────────────────────


class TestBridgeServer:
    def _client(self, bridge):
        address = bridge.address
        if address.kind == "unix":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(address.path)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((address.host, address.port))
        return sock

    def _send(self, bridge, payload):
        import json

        with self._client(bridge) as sock:
            sock.settimeout(5)
            sock.sendall((json.dumps(payload) + "\n").encode())
            return json.loads(sock.makefile("r", encoding="utf-8").readline())

    def test_a_valid_call_reaches_the_handler(self) -> None:
        calls = []
        with BridgeServer(recording_invoker(calls, result="rows")) as bridge:
            response = self._send(bridge, {
                "id": 1, "token": bridge.address.token,
                "binding": "WAREHOUSE", "method": "query", "kwargs": {"sql": "x"},
            })
        assert response["ok"] and response["result"] == "rows"
        assert calls == [("WAREHOUSE", "query", {"sql": "x"})]

    def test_a_wrong_token_is_rejected(self) -> None:
        calls = []
        with BridgeServer(recording_invoker(calls)) as bridge:
            response = self._send(bridge, {
                "id": 1, "token": "not-the-token",
                "binding": "WAREHOUSE", "method": "query", "kwargs": {},
            })
        assert not response["ok"] and response["error"] == "unauthorized"
        assert calls == []  # the handler was never reached

    def test_a_missing_token_is_rejected(self) -> None:
        calls = []
        with BridgeServer(recording_invoker(calls)) as bridge:
            response = self._send(bridge, {"binding": "X", "method": "y"})
        assert not response["ok"]
        assert calls == []

    def test_malformed_json_does_not_kill_the_bridge(self) -> None:
        import json

        with BridgeServer(recording_invoker([])) as bridge:
            with self._client(bridge) as sock:
                sock.settimeout(5)
                sock.sendall(b"{not json\n")
                reader = sock.makefile("r", encoding="utf-8")
                assert not json.loads(reader.readline())["ok"]
                # Still serving.
                sock.sendall((json.dumps({
                    "token": bridge.address.token, "binding": "A", "method": "b",
                }) + "\n").encode())
                assert json.loads(reader.readline())["ok"]

    def test_a_raising_handler_is_reported_as_data(self) -> None:
        with BridgeServer(recording_invoker([], fail=True)) as bridge:
            response = self._send(bridge, {
                "token": bridge.address.token, "binding": "A", "method": "b",
            })
        assert not response["ok"]
        assert "denied by policy" in response["error"]

    def test_the_call_ceiling_is_enforced(self) -> None:
        calls = []
        limits = BridgeLimits(max_calls=3)
        with BridgeServer(recording_invoker(calls), limits=limits) as bridge:
            responses = [
                self._send(bridge, {
                    "token": bridge.address.token, "binding": "A", "method": "b",
                })
                for _ in range(5)
            ]
        assert [r["ok"] for r in responses] == [True, True, True, False, False]
        assert len(calls) == 3
        assert "call limit" in responses[3]["error"]

    def test_calls_are_recorded_for_the_transcript(self) -> None:
        with BridgeServer(recording_invoker([])) as bridge:
            self._send(bridge, {
                "token": bridge.address.token, "binding": "LINEAR",
                "method": "create_issue", "kwargs": {"title": "x"},
            })
            summary = bridge.summary()
        assert summary["calls"] == 1
        assert summary["bindings"] == ["LINEAR"]
        assert bridge.calls[0].method == "create_issue"

    @pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="POSIX only")
    def test_the_unix_socket_is_not_world_accessible(self) -> None:
        # The filesystem is doing the access control here, not the token.
        with BridgeServer(recording_invoker([])) as bridge:
            directory = os.path.dirname(bridge.address.path)
            assert os.stat(directory).st_mode & 0o077 == 0

    def test_stop_cleans_up_the_socket(self) -> None:
        bridge = BridgeServer(recording_invoker([]))
        bridge.start()
        path = bridge.address.path
        bridge.stop()
        if path:
            assert not os.path.exists(path)


# ── the preamble ─────────────────────────────────────────────────────────


class TestPreamble:
    def test_it_is_valid_python(self) -> None:
        import ast

        ast.parse(build_preamble(BINDINGS))

    def test_the_binding_spec_is_inlined(self) -> None:
        rendered = build_preamble(BINDINGS)
        assert "WAREHOUSE" in rendered and "create_issue" in rendered
        assert "__SHIPIT_BINDING_SPEC__" not in rendered

    def test_it_imports_nothing_from_shipit(self) -> None:
        # The sandbox must not be able to reach the tools or the gate.
        assert "shipit" not in build_preamble(BINDINGS).replace("shipit code mode", "")


# ── end to end ───────────────────────────────────────────────────────────


class TestExecuteCode:
    def test_plain_python_runs_and_stdout_is_returned(self) -> None:
        out = run_code("print(2 + 2)")
        assert out.text.strip() == "4"
        assert out.metadata["exit_code"] == 0

    def test_env_calls_reach_the_parent(self) -> None:
        calls = []
        out = run_code(
            'print(env.WAREHOUSE.query(sql="SELECT 1"))',
            invoker=recording_invoker(calls, result="42 rows"),
            calls=calls,
        )
        assert "42 rows" in out.text
        assert calls == [("WAREHOUSE", "query", {"sql": "SELECT 1"})]

    def test_several_bindings_compose_in_one_call(self) -> None:
        """The reason execute_code exists: five tool calls become one."""
        calls = []
        out = run_code(
            """
rows = env.WAREHOUSE.query(sql="SELECT account FROM bookings")
for account in ["northwind", "globex"]:
    env.LINEAR.create_issue(title=f"Check in on {account}")
print("filed", 2)
""",
            invoker=recording_invoker(calls),
            calls=calls,
        )
        assert "filed 2" in out.text
        assert [c[0] for c in calls] == ["WAREHOUSE", "LINEAR", "LINEAR"]
        assert calls[1][2] == {"title": "Check in on northwind"}

    def test_env_calls_are_reported_in_metadata(self) -> None:
        calls = []
        out = run_code(
            'env.LINEAR.get_issue(id=1)',
            invoker=recording_invoker(calls), calls=calls,
        )
        assert out.metadata["env_calls"] == 1
        assert out.metadata["env_bindings_used"] == ["LINEAR"]
        assert out.metadata["calls"][0]["method"] == "get_issue"

    def test_a_refused_call_surfaces_in_the_child(self) -> None:
        out = run_code(
            'env.LINEAR.create_issue(title="x")',
            invoker=recording_invoker([], fail=True),
        )
        assert "denied by policy" in out.text
        assert out.metadata["exit_code"] != 0

    def test_an_unknown_method_fails_without_a_round_trip(self) -> None:
        calls = []
        out = run_code("env.LINEAR.no_such_method()", calls=calls)
        assert "no method" in out.text
        assert calls == []  # caught in the child from the inlined spec

    def test_an_unknown_binding_lists_what_exists(self) -> None:
        out = run_code("env.NOPE.thing()")
        assert "No binding named" in out.text
        assert "WAREHOUSE" in out.text

    def test_dir_env_works(self) -> None:
        assert "WAREHOUSE" in run_code("print(sorted(dir(env)))").text


class TestSandboxBoundary:
    """The child must not be able to reach what the parent is protecting."""

    def test_parent_environment_secrets_are_not_inherited(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_SECRET_API_KEY", "sk-live-do-not-leak")
        out = run_code("import os; print(os.environ.get('MY_SECRET_API_KEY'))")
        assert "sk-live-do-not-leak" not in out.text
        assert "None" in out.text

    def test_importing_shipit_in_the_child_yields_no_credentials(self) -> None:
        """The boundary protects live secrets, not the import system.

        shipit is installed, so the child can import it — that is not the
        claim. The claim is that doing so gets a fresh, empty process: the
        parent's populated CredentialStore lives in the parent's memory and
        does not cross the socket.
        """
        out = run_code(
            "from shipit_agent.integrations import InMemoryCredentialStore\n"
            "print('records:', len(InMemoryCredentialStore().list()))"
        )
        assert "records: 0" in out.text

    def test_the_child_holds_no_tool_objects(self) -> None:
        # Only a socket. There is no in-process handle to bypass the gate with.
        out = run_code(
            "print(sorted(k for k in dir(env) if not k.startswith('_')))"
        )
        assert "WAREHOUSE" in out.text
        assert "credential" not in out.text.lower()

    def test_the_bridge_token_is_the_only_credential_present(self) -> None:
        out = run_code(
            "import os\n"
            "print([k for k in sorted(os.environ) if 'KEY' in k or 'TOKEN' in k])"
        )
        # Only the bridge token, which authorizes gated calls — not raw secrets.
        assert "SHIPIT_BRIDGE_TOKEN" in out.text
        assert "API_KEY" not in out.text

    def test_code_mode_off_means_env_is_not_offered(self) -> None:
        out = ExecuteCodeTool().run(
            ToolContext(prompt="x", state={BINDINGS_STATE_KEY: BINDINGS}),
            code="print(1)",
        )
        assert out.metadata["error"] == "codemode_disabled"
        assert "not enabled" in out.text

    def test_every_env_call_goes_through_the_supplied_gate(self) -> None:
        # There is no path from the child to a tool that skips the invoker.
        calls = []
        run_code(
            "for i in range(3): env.LINEAR.get_issue(id=i)",
            invoker=recording_invoker(calls), calls=calls,
        )
        assert len(calls) == 3


class TestFailureModes:
    def test_empty_code_is_refused(self) -> None:
        out = run_code("   ")
        assert out.metadata["error"] == "missing_code"

    def test_a_syntax_error_is_reported(self) -> None:
        out = run_code("def broken(:\n    pass")
        assert "SyntaxError" in out.text

    def test_a_traceback_points_at_the_models_own_lines(self) -> None:
        # Without re-basing, a 2-line snippet reports "line 180-something".
        out = run_code("x = 1\nraise ValueError('boom')")
        assert "boom" in out.text
        assert "line 2" in out.text

    def test_a_timeout_is_reported_not_hung(self) -> None:
        out = run_code("import time; time.sleep(30)", timeout_seconds=1)
        assert out.metadata["timed_out"]
        assert "timed out" in out.text

    def test_the_call_ceiling_stops_a_runaway_loop(self) -> None:
        calls = []
        out = run_code(
            "for i in range(500):\n"
            "    try: env.LINEAR.get_issue(id=i)\n"
            "    except Exception as e: print('stopped:', e); break",
            invoker=recording_invoker(calls),
            calls=calls,
            limits=BridgeLimits(max_calls=5),
        )
        assert "call limit" in out.text
        assert len(calls) == 5

    def test_no_output_says_so_rather_than_returning_nothing(self) -> None:
        assert "no output" in run_code("x = 1").text

    def test_large_output_is_clipped(self) -> None:
        out = run_code("print('x' * 100000)")
        assert len(out.text) < 20_000
