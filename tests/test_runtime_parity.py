"""The two loops must not drift apart again.

runtime.py and async_runtime.py are two implementations of one loop, and they
have drifted repeatedly and silently. Before RuntimeCore, ten capabilities —
guardrails, healing, compaction, lockdown, cancellation, usage ticks — existed
only in the sync one. Nobody decided that.

These tests assert the shared decisions really are shared, and that both loops
behave identically where it matters.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.lockdown import LockdownState
from shipit_agent.models import ToolCall
from shipit_agent.permissions import PermissionEngine
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_core import RuntimeCore
from shipit_agent.tools.base import ToolOutput

SHARED = [
    name for name in vars(RuntimeCore)
    if not name.startswith("__") and name != "_init_core"
]


def tool(name, *, output="ok", sensitive=False, calls=None):
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
                calls.append(name)
            return ToolOutput(
                text=output, metadata={"sensitive": True} if sensitive else {}
            )

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
            usage={"total_tokens": 100},
        )


def run_sync(script, tools, **kwargs):
    runtime = AgentRuntime(llm=ScriptedLLM(script), prompt="p", tools=tools,
                           max_iterations=5, **kwargs)
    return runtime.run("go")


def run_async(script, tools, **kwargs):
    runtime = AsyncAgentRuntime(llm=ScriptedLLM(script), prompt="p", tools=tools,
                                max_iterations=5, **kwargs)
    return asyncio.run(runtime.run("go"))


class TestStructuralParity:
    def test_both_inherit_the_shared_core(self) -> None:
        assert issubclass(AgentRuntime, RuntimeCore)
        assert issubclass(AsyncAgentRuntime, RuntimeCore)

    @pytest.mark.parametrize("name", SHARED)
    def test_neither_loop_overrides_a_shared_decision(self, name) -> None:
        """An override is how drift starts — it is a copy by another name."""
        for cls in (AgentRuntime, AsyncAgentRuntime):
            assert name not in vars(cls), f"{cls.__name__} overrides {name}"

    def test_both_accept_the_same_control_plane_options(self) -> None:
        sync = set(inspect.signature(AgentRuntime.__init__).parameters)
        asyn = set(inspect.signature(AsyncAgentRuntime.__init__).parameters)
        for option in ("permissions", "guardrails", "approvals", "lockdown",
                       "heal_tool_calls", "code_mode", "context_window_tokens",
                       "hooks", "retry_policy", "max_iterations"):
            assert option in sync, f"sync is missing {option}"
            assert option in asyn, f"async is missing {option}"


class TestBehaviouralParity:
    """The same inputs must produce the same decisions in both loops."""

    def _both(self, script, make_tools, **kwargs):
        sync_calls: list = []
        async_calls: list = []
        sync = run_sync(script, make_tools(sync_calls), **kwargs)
        asyn = run_async(script, make_tools(async_calls), **kwargs)
        return (sync, sync_calls), (asyn, async_calls)

    def test_permissions_deny_identically(self) -> None:
        (_, s), (_, a) = self._both(
            [("", [("bash", {"path": "x"})]), ("done", [])],
            lambda calls: [tool("bash", calls=calls)],
            permissions=PermissionEngine(deny=["bash"]),
        )
        assert s == a == []

    def test_lockdown_latches_identically(self) -> None:
        (_, s), (_, a) = self._both(
            [
                ("", [("secrets", {"path": "x"})]),
                ("", [("slack", {"channel": "#c"})]),
                ("done", []),
            ],
            lambda calls: [tool("secrets", sensitive=True, calls=calls),
                           tool("slack", calls=calls)],
        )
        assert s == a == ["secrets"]

    def test_guardrails_block_input_identically(self) -> None:
        from shipit_agent import Guardrails

        rails = Guardrails(input_blocklist=["forbidden"])
        sync = AgentRuntime(llm=ScriptedLLM([("x", [])]), prompt="p",
                            guardrails=rails).run("this is forbidden")
        asyn = asyncio.run(
            AsyncAgentRuntime(llm=ScriptedLLM([("x", [])]), prompt="p",
                              guardrails=rails).run("this is forbidden")
        )
        assert "blocked by guardrails" in sync[1].content
        assert "blocked by guardrails" in asyn[1].content

    def test_usage_is_tracked_and_ticked_in_both(self) -> None:
        for state, _ in (run_sync([("done", [])], []),
                         run_async([("done", [])], [])):
            ticks = [e for e in state.events if e.type == "usage_tick"]
            assert ticks, "no usage_tick emitted"
            assert ticks[-1].payload["usage"]["total_tokens"] == 100

    def test_healing_promotes_text_tool_calls_in_both(self) -> None:
        script = [('<tool_call>{"name": "read_it", "arguments": {}}</tool_call>', []),
                  ("done", [])]
        for _, calls in (self._both(script, lambda c: [tool("read_it", calls=c)])):
            assert calls == ["read_it"], "healing did not fire"

    def test_give_up_is_surfaced_in_both(self) -> None:
        from shipit_agent.tools.give_up import GiveUpTool

        script = [("", [("give_up", {"reason": "no credentials"})]), ("x", [])]
        for runtime_cls, runner in ((AgentRuntime, run_sync),
                                    (AsyncAgentRuntime, run_async)):
            runtime = runtime_cls(llm=ScriptedLLM(script), prompt="p",
                                  tools=[GiveUpTool()], max_iterations=4)
            if runtime_cls is AgentRuntime:
                runtime.run("go")
            else:
                asyncio.run(runtime.run("go"))
            assert runtime.metadata["gave_up"] is True
            assert runtime.metadata["give_up_reason"] == "no credentials"

    def test_both_publish_the_same_tool_state(self) -> None:
        from shipit_agent.tools.connections.connections_tool import (
            REGISTRY_STATE_KEY,
        )
        from shipit_agent.tools.sub_agent.sub_agent_tool import PARENT_STATE_KEY

        seen: dict[str, set] = {}

        def probe(label):
            class P:
                name = "probe"
                description = "p"
                prompt_instructions = ""

                def schema(self):
                    return {"function": {"name": "probe", "parameters": {}}}

                def run(self, context, **kwargs):
                    seen[label] = set(context.state)
                    return ToolOutput(text="ok")

            return P()

        script = [("", [("probe", {})]), ("done", [])]
        run_sync(script, [probe("sync")])
        run_async(script, [probe("async")])
        assert seen["sync"] == seen["async"]
        assert {REGISTRY_STATE_KEY, PARENT_STATE_KEY, "memory_store"} <= seen["sync"]

    def test_tool_denied_carries_the_same_payload_in_both(self) -> None:
        """The exact drift that started this: fixed in one loop, not the other."""
        for state, _ in (
            run_sync([("", [("bash", {"path": "x"})]), ("done", [])],
                     [tool("bash")], permissions=PermissionEngine(deny=["bash"])),
            run_async([("", [("bash", {"path": "x"})]), ("done", [])],
                      [tool("bash")], permissions=PermissionEngine(deny=["bash"])),
        ):
            denied = [e for e in state.events if e.type == "tool_denied"]
            assert denied
            assert denied[0].payload["tool"] == "bash"
            assert denied[0].payload["call_id"]


class TestCore:
    def test_cancellation_is_shared(self) -> None:
        runtime = AgentRuntime(llm=ScriptedLLM([("x", [])]), prompt="p")
        assert not runtime.cancelled
        runtime.cancel()
        assert runtime.cancelled

    def test_lockdown_outranks_an_allow_rule(self) -> None:
        core = AgentRuntime(llm=ScriptedLLM([]), prompt="p",
                            permissions=PermissionEngine(allow=["*"]))
        core.lockdown = LockdownState()
        core.lockdown.engage(reason="read secrets", tool="db", source="declared")
        decision = core.authorize("slack", {}, tool("slack"))
        assert decision is not None and decision.denied


class TestSharedStateIsActuallyShared:
    """Both loops must *use* build_shared_state, not just have identical keys.

    The sync loop kept building its state inline after RuntimeCore landed. The
    key-comparison test passed because both happened to produce the same keys —
    so when the sub-agent event sink was added to the core, only the async loop
    got it. This asserts the source of the state, not just its shape.
    """

    def test_neither_loop_builds_tool_state_inline(self) -> None:
        import pathlib

        for name in ("runtime.py", "async_runtime.py"):
            src = pathlib.Path("shipit_agent") / name
            text = src.read_text()
            assert "build_shared_state(registry" in text, f"{name} must use the core"
            assert 'shared_state["available_tools"]' not in text, (
                f"{name} builds tool state inline — it will drift"
            )

    def test_the_subagent_event_sink_is_published_by_both(self) -> None:
        from shipit_agent.tools.sub_agent.sub_agent_tool import EVENT_SINK_KEY

        seen: dict[str, set] = {}

        def probe(label):
            class P:
                name = "probe"
                description = "p"
                prompt_instructions = ""

                def schema(self):
                    return {"function": {"name": "probe", "parameters": {}}}

                def run(self, context, **kwargs):
                    seen[label] = set(context.state)
                    return ToolOutput(text="ok")

            return P()

        script = [("", [("probe", {})]), ("done", [])]
        run_sync(script, [probe("sync")])
        run_async(script, [probe("async")])
        assert EVENT_SINK_KEY in seen["sync"]
        assert EVENT_SINK_KEY in seen["async"]
        assert seen["sync"] == seen["async"]
