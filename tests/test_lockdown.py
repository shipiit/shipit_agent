"""Lockdown — read something sensitive, and the run may only keep reading."""

from __future__ import annotations

import pytest

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.lockdown import (
    LockdownPolicy,
    LockdownState,
    coerce_lockdown,
)
from shipit_agent.models import ToolCall
from shipit_agent.permissions import PermissionEngine
from shipit_agent.tools.base import ToolOutput


def tool(name, *, output="ok", sensitive=False, reason=None, calls=None):
    class T:
        def __init__(self):
            self.name = name
            self.description = name
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {"properties": {
                "path": {"type": "string"}, "channel": {"type": "string"}}}}}

        def run(self, context, **kwargs):
            if calls is not None:
                calls.append((name, kwargs))
            metadata = {"sensitive": True} if sensitive else {}
            if reason:
                metadata["sensitive_reason"] = reason
            return ToolOutput(text=output, metadata=metadata)

    return T()


class ScriptedLLM:
    model = "m"

    def __init__(self, script):
        self.script = list(script)
        self.n = 0

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        step = self.script[self.n] if self.n < len(self.script) else ("done", [])
        self.n += 1
        return LLMResponse(
            content=step[0],
            tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
        )


def run_agent(script, tools, **kwargs):
    kwargs.setdefault("auto_use_skills", False)
    kwargs.setdefault("max_iterations", 6)
    return Agent(llm=ScriptedLLM(script), tools=tools, **kwargs).run("go")


class TestTheHole:
    def test_without_lockdown_the_agent_can_exfiltrate(self) -> None:
        """The behaviour lockdown exists to stop."""
        calls: list = []
        run_agent(
            [
                ("", [("read_customers", {"path": "customers.csv"})]),
                ("", [("slack", {"channel": "#public"})]),
                ("done", []),
            ],
            [
                tool("read_customers", output="alice@x.com, bob@y.com", calls=calls),
                tool("slack", calls=calls),
            ],
            lockdown=False,
        )
        assert [n for n, _ in calls] == ["read_customers", "slack"]

    def test_with_lockdown_the_send_is_blocked(self) -> None:
        calls: list = []
        result = run_agent(
            [
                ("", [("read_customers", {"path": "customers.csv"})]),
                ("", [("slack", {"channel": "#public"})]),
                ("I can't send that.", []),
            ],
            [
                tool("read_customers", output="alice@x.com", sensitive=True, calls=calls),
                tool("slack", calls=calls),
            ],
        )
        assert [n for n, _ in calls] == ["read_customers"]  # slack never ran
        blocked = [m for m in result.messages if m.role == "tool"][1]
        assert "Lockdown" in blocked.content


class TestLatching:
    def test_a_declaration_latches_it(self) -> None:
        state = LockdownState()
        trigger = state.observe(
            tool="read_customers", arguments={},
            output_metadata={"sensitive": True},
        )
        assert trigger is not None and state.engaged
        assert trigger.source == "declared"

    def test_a_custom_reason_is_carried(self) -> None:
        state = LockdownState()
        state.observe(
            tool="hr", arguments={},
            output_metadata={"sensitive": True, "sensitive_reason": "salary data"},
        )
        assert state.trigger.reason == "salary data"

    def test_an_ordinary_read_does_not_latch(self) -> None:
        state = LockdownState()
        assert state.observe(tool="read_file", arguments={}, output_metadata={}) is None
        assert not state.engaged

    def test_it_is_one_way(self) -> None:
        # No un-latch: a mechanism that could be switched off mid-run is a
        # mechanism the model could be talked into switching off.
        state = LockdownState()
        state.observe(tool="a", arguments={}, output_metadata={"sensitive": True})
        first = state.trigger
        state.observe(tool="b", arguments={}, output_metadata={"sensitive": True})
        assert state.trigger is first
        assert not hasattr(state, "disengage")

    def test_disabled_never_latches(self) -> None:
        state = LockdownState(policy=LockdownPolicy(enabled=False))
        state.observe(tool="a", arguments={}, output_metadata={"sensitive": True})
        assert not state.engaged

    def test_declarations_can_be_ignored(self) -> None:
        state = LockdownState(policy=LockdownPolicy(honour_declarations=False))
        state.observe(tool="a", arguments={}, output_metadata={"sensitive": True})
        assert not state.engaged


class TestPathDetection:
    def test_a_matching_path_latches(self) -> None:
        state = LockdownState(policy=LockdownPolicy(sensitive_paths=("*.env",)))
        trigger = state.observe(tool="read_file", arguments={"path": ".env"},
                                output_metadata={})
        assert trigger is not None and trigger.source == "path"
        assert ".env" in trigger.reason

    def test_globs_work(self) -> None:
        state = LockdownState(policy=LockdownPolicy(sensitive_paths=("**/secrets/**",)))
        assert state.observe(tool="read_file",
                             arguments={"path": "app/secrets/keys.json"},
                             output_metadata={})

    def test_detection_is_off_by_default(self) -> None:
        # A false positive costs every remaining action in the run.
        state = LockdownState()
        assert state.observe(tool="read_file", arguments={"path": ".env"},
                             output_metadata={}) is None

    @pytest.mark.parametrize("key", ["path", "file", "url", "query"])
    def test_several_argument_names_are_checked(self, key) -> None:
        state = LockdownState(policy=LockdownPolicy(sensitive_paths=("*secret*",)))
        assert state.observe(tool="x", arguments={key: "my-secret-thing"},
                             output_metadata={})

    def test_a_non_matching_path_does_not_latch(self) -> None:
        state = LockdownState(policy=LockdownPolicy(sensitive_paths=("*.env",)))
        assert state.observe(tool="read_file", arguments={"path": "app.py"},
                             output_metadata={}) is None


class TestEnforcement:
    def _locked(self, **policy):
        state = LockdownState(policy=LockdownPolicy(**policy))
        state.engage(reason="read the customer list", tool="db", source="declared")
        return state

    def test_actions_are_blocked(self) -> None:
        assert self._locked().blocks("slack", read_only=False)

    def test_observations_still_run(self) -> None:
        # Reading is how the agent finishes; acting is how data gets out.
        assert not self._locked().blocks("read_file", read_only=True)

    def test_the_human_facing_tools_stay_available(self) -> None:
        # Removing the ability to say "I locked down" makes it look like a hang.
        state = self._locked()
        for name in ("ask_user", "human_review", "give_up"):
            assert not state.blocks(name, read_only=False), name

    def test_the_allowlist_is_configurable(self) -> None:
        assert not self._locked(always_allowed=("slack",)).blocks(
            "slack", read_only=False
        )

    def test_nothing_is_blocked_before_latching(self) -> None:
        assert not LockdownState().blocks("slack", read_only=False)

    def test_the_denial_explains_itself(self) -> None:
        reason = self._locked().denial_reason("slack")
        assert "read the customer list" in reason
        assert "Do not retry" in reason
        assert "report what you found" in reason


class TestRuntimeIntegration:
    def test_it_outranks_an_explicit_allow_rule(self) -> None:
        """No configuration set before the read may authorize an action after it."""
        calls: list = []
        run_agent(
            [
                ("", [("secrets", {"path": "x"})]),
                ("", [("slack", {"channel": "#c"})]),
                ("done", []),
            ],
            [tool("secrets", sensitive=True, calls=calls), tool("slack", calls=calls)],
            permissions=PermissionEngine(allow=["*"]),
        )
        assert [n for n, _ in calls] == ["secrets"]

    def test_reads_after_lockdown_still_work(self) -> None:
        calls: list = []
        run_agent(
            [
                ("", [("secrets", {"path": "x"})]),
                ("", [("read_file", {"path": "a.py"})]),
                ("done", []),
            ],
            [tool("secrets", sensitive=True, calls=calls),
             tool("read_file", calls=calls)],
        )
        assert [n for n, _ in calls] == ["secrets", "read_file"]

    def test_an_event_is_emitted(self) -> None:
        result = run_agent(
            [("", [("secrets", {"path": "x"})]), ("done", [])],
            [tool("secrets", sensitive=True, reason="customer PII")],
        )
        events = [e for e in result.events if e.type == "lockdown_engaged"]
        assert len(events) == 1
        assert events[0].payload["reason"] == "customer PII"
        assert events[0].payload["source"] == "declared"

    def test_it_latches_only_once(self) -> None:
        result = run_agent(
            [
                ("", [("secrets", {"path": "a"})]),
                ("", [("secrets", {"path": "b"})]),
                ("done", []),
            ],
            [tool("secrets", sensitive=True)],
        )
        assert len([e for e in result.events if e.type == "lockdown_engaged"]) == 1

    def test_path_policy_works_end_to_end(self) -> None:
        calls: list = []
        run_agent(
            [
                ("", [("read_file", {"path": ".env"})]),
                ("", [("slack", {"channel": "#c"})]),
                ("done", []),
            ],
            [tool("read_file", calls=calls), tool("slack", calls=calls)],
            lockdown=LockdownPolicy(sensitive_paths=("*.env",)),
        )
        assert [n for n, _ in calls] == ["read_file"]

    def test_nothing_changes_when_no_tool_declares_anything(self) -> None:
        calls: list = []
        run_agent(
            [
                ("", [("read_file", {"path": "a.py"})]),
                ("", [("slack", {"channel": "#c"})]),
                ("done", []),
            ],
            [tool("read_file", calls=calls), tool("slack", calls=calls)],
        )
        assert [n for n, _ in calls] == ["read_file", "slack"]


class TestCoercion:
    def test_none_and_true_give_the_default_policy(self) -> None:
        assert coerce_lockdown(None).policy.enabled
        assert coerce_lockdown(True).policy.honour_declarations

    def test_false_disables(self) -> None:
        assert not coerce_lockdown(False).policy.enabled

    def test_a_policy_passes_through(self) -> None:
        policy = LockdownPolicy(sensitive_paths=("*.env",))
        assert coerce_lockdown(policy).policy is policy

    def test_a_dict_becomes_a_policy(self) -> None:
        assert coerce_lockdown({"sensitive_paths": ("*.pem",)}).policy.sensitive_paths

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            coerce_lockdown("yes")

    def test_serializable(self) -> None:
        import json

        state = LockdownState()
        state.engage(reason="r", tool="t", source="declared")
        assert json.dumps(state.to_dict())
