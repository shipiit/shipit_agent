"""Tests for the permission engine, blocking/modifying hooks, and plan mode."""

from __future__ import annotations

from typing import Any

from shipit_agent import (
    Agent,
    AgentHooks,
    FunctionTool,
    PermissionDecision,
    PermissionEngine,
    PermissionResult,
)
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.permissions import authorize_tool, coerce_permissions


# ---------------------------------------------------------------------------
# Mock LLMs
# ---------------------------------------------------------------------------


class CallThenDone:
    """Calls one tool on the first turn, then answers."""

    def __init__(self, tool_name: str, args: dict[str, Any] | None = None):
        self.tool_name = tool_name
        self.args = args or {}
        self._n = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self._n += 1
        if self._n == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name=self.tool_name, arguments=self.args)],
            )
        return LLMResponse(content="done")


def _recording_tool(name: str, sink: list[str]) -> FunctionTool:
    def _fn(**kwargs: Any) -> str:
        sink.append(name)
        return f"{name} ran"

    return FunctionTool.from_callable(_fn, name=name)


# ---------------------------------------------------------------------------
# PermissionEngine — modes & rules
# ---------------------------------------------------------------------------


class TestPermissionEngine:
    def test_default_allows_unmatched(self) -> None:
        e = PermissionEngine()
        assert e.check("anything", {}).allowed

    def test_deny_rule_wins(self) -> None:
        e = PermissionEngine(deny=["bash"])
        assert e.check("bash", {}).denied
        assert e.check("read_file", {}).allowed

    def test_deny_wins_even_in_bypass(self) -> None:
        e = PermissionEngine(mode="bypass", deny=["danger*"])
        assert e.check("danger_zone", {}).denied
        assert e.check("anything_else", {}).allowed

    def test_glob_rules(self) -> None:
        e = PermissionEngine(deny=["*_delete", "git*"])
        assert e.check("record_delete", {}).denied
        assert e.check("github", {}).denied
        assert e.check("read", {}).allowed

    def test_ask_rule(self) -> None:
        e = PermissionEngine(ask=["bash"])
        assert e.check("bash", {}).needs_approval

    def test_plan_mode_denies_mutating_allows_readonly(self) -> None:
        e = PermissionEngine(mode="plan")
        assert e.check("write_file", {}).denied
        assert e.check("bash", {}).denied
        assert e.check("read_file", {}).allowed
        assert e.check("grep_files", {}).allowed
        assert e.check("web_search", {}).allowed

    def test_plan_mode_allow_list_overrides(self) -> None:
        e = PermissionEngine(mode="plan", allow=["bash"])
        assert e.check("bash", {}).allowed

    def test_accept_edits_auto_allows_edits(self) -> None:
        e = PermissionEngine(mode="acceptEdits")
        assert e.check("edit_file", {}).allowed
        assert e.check("write_file", {}).allowed

    def test_read_only_attribute_wins_over_name(self) -> None:
        e = PermissionEngine(mode="plan")

        class T:
            read_only = True

        # name looks mutating, but the tool declares itself read-only
        assert e.check("write_thing", {}, tool=T()).allowed

    def test_callback_consulted(self) -> None:
        def cb(name, args):
            if name == "bash":
                return PermissionResult(PermissionDecision.DENY, reason="no shell")
            return None

        e = PermissionEngine(callback=cb)
        assert e.check("bash", {}).denied
        assert e.check("read", {}).allowed  # callback returned None → default

    def test_argument_rewrite(self) -> None:
        def cb(name, args):
            return PermissionResult(
                PermissionDecision.ALLOW, updated_arguments={"path": "/safe"}
            )

        e = PermissionEngine(ask=["write*"], callback=cb)
        result = e.check("write_file", {"path": "/etc/passwd"})
        assert result.allowed
        assert result.updated_arguments == {"path": "/safe"}


class TestCoercePermissions:
    def test_none(self) -> None:
        assert coerce_permissions(None) is None

    def test_mode_string(self) -> None:
        e = coerce_permissions("plan")
        assert isinstance(e, PermissionEngine) and e.mode == "plan"

    def test_dict(self) -> None:
        e = coerce_permissions({"mode": "bypass", "deny": ["x"]})
        assert e.mode == "bypass" and e.deny == ["x"]

    def test_engine_passthrough(self) -> None:
        src = PermissionEngine(mode="acceptEdits")
        assert coerce_permissions(src) is src


# ---------------------------------------------------------------------------
# Blocking / modifying hooks
# ---------------------------------------------------------------------------


class TestBlockingHooks:
    def test_hook_deny_dict(self) -> None:
        hooks = AgentHooks()

        @hooks.on_before_tool
        def guard(name, args):
            if name == "bash":
                return {"decision": "deny", "reason": "blocked"}
            return None

        decision = hooks.run_before_tool("bash", {})
        assert decision is not None and decision.denied

    def test_hook_false_denies(self) -> None:
        hooks = AgentHooks()
        hooks.on_before_tool(lambda name, args: False)
        assert hooks.run_before_tool("x", {}).denied

    def test_hook_none_is_observe_only(self) -> None:
        hooks = AgentHooks()
        seen = []
        hooks.on_before_tool(lambda name, args: seen.append(name))
        assert hooks.run_before_tool("x", {}) is None
        assert seen == ["x"]

    def test_hook_rewrites_arguments(self) -> None:
        hooks = AgentHooks()

        @hooks.on_before_tool
        def rewrite(name, args):
            return PermissionResult(
                PermissionDecision.ALLOW, updated_arguments={"safe": True}
            )

        decision = hooks.run_before_tool("x", {})
        assert decision.updated_arguments == {"safe": True}

    def test_user_prompt_hook_rewrites(self) -> None:
        hooks = AgentHooks()
        hooks.on_user_prompt(lambda p: p.replace("SECRET", "[redacted]"))
        prompt, decision = hooks.run_user_prompt("my SECRET key")
        assert prompt == "my [redacted] key" and decision is None


class TestAuthorizeTool:
    def test_deny_wins_over_allow(self) -> None:
        hooks = AgentHooks()
        hooks.on_before_tool(lambda n, a: {"decision": "deny", "reason": "no"})
        engine = PermissionEngine()  # would allow
        decision = authorize_tool(hooks, engine, "x", {})
        assert decision.denied

    def test_none_when_no_opinion(self) -> None:
        assert authorize_tool(None, None, "x", {}) is None


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------


class TestAgentIntegration:
    def test_deny_rule_blocks_tool(self) -> None:
        ran: list[str] = []
        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", ran)],
            permissions=PermissionEngine(deny=["bash"]),
            auto_use_skills=False,
        )
        result = agent.run("use bash")
        assert ran == []  # tool never executed
        denied = [
            m for m in result.messages
            if m.role == "tool" and m.metadata.get("error") == "permission_denied"
        ]
        assert denied and "was NOT run" in denied[0].content

    def test_plan_mode_blocks_writes(self) -> None:
        ran: list[str] = []
        agent = Agent(
            llm=CallThenDone("write_file", {"path": "x"}),
            tools=[_recording_tool("write_file", ran)],
            permission_mode="plan",
            auto_use_skills=False,
        )
        agent.run("write a file")
        assert ran == []  # plan mode is read-only

    def test_plan_method(self) -> None:
        ran: list[str] = []
        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", ran)],
            auto_use_skills=False,
        )
        agent.plan("do something")
        assert ran == []
        # plan() must not mutate the agent's normal mode
        assert agent.permission_mode == "default"

    def test_callback_approval(self) -> None:
        ran: list[str] = []
        decisions = {"bash": PermissionDecision.DENY}

        def cb(name, args):
            return PermissionResult(decisions.get(name, PermissionDecision.ALLOW))

        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", ran)],
            permission_callback=cb,
            auto_use_skills=False,
        )
        agent.run("use bash")
        assert ran == []  # callback denied it

    def test_hook_blocks_in_agent(self) -> None:
        ran: list[str] = []
        hooks = AgentHooks()

        @hooks.on_before_tool
        def guard(name, args):
            return {"decision": "deny", "reason": "policy"} if name == "bash" else None

        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", ran)],
            hooks=hooks,
            auto_use_skills=False,
        )
        agent.run("use bash")
        assert ran == []

    def test_default_agent_unrestricted(self) -> None:
        ran: list[str] = []
        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", ran)],
            auto_use_skills=False,
        )
        agent.run("use bash")
        assert ran == ["bash"]  # no permissions set → runs as before

    def test_argument_rewrite_applied(self) -> None:
        captured: dict[str, Any] = {}

        def tool_fn(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "ok"

        def cb(name, args):
            return PermissionResult(
                PermissionDecision.ALLOW, updated_arguments={"path": "/safe"}
            )

        agent = Agent(
            llm=CallThenDone("write_file", {"path": "/etc/passwd"}),
            tools=[FunctionTool.from_callable(tool_fn, name="write_file")],
            permissions=PermissionEngine(callback=cb),
            auto_use_skills=False,
        )
        agent.run("write")
        assert captured.get("path") == "/safe"  # rewritten before execution

    def test_tool_denied_event_emitted(self) -> None:
        agent = Agent(
            llm=CallThenDone("bash"),
            tools=[_recording_tool("bash", [])],
            permissions=PermissionEngine(deny=["bash"]),
            auto_use_skills=False,
        )
        result = agent.run("use bash")
        assert any(e.type == "tool_denied" for e in result.events)
