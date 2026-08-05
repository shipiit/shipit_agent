"""Deferred approvals — queue, decide later, auto-approve by kind."""

from __future__ import annotations

import threading

import pytest

from shipit_agent.approvals import ActionState, ApprovalQueue, coerce_queue
from shipit_agent.tools.contracts import ActionKind, ToolContract

SEND = ActionKind("comms.send", "Send a message on your behalf")
DEPLOY = ActionKind("deploy.write", "Deploy a service")

AUTO_OK = ToolContract(action_kind=SEND, auto_approvable=True, implements_revert=True)
MANUAL = ToolContract(action_kind=DEPLOY, destructive=True, await_decision=True)
UNTAGGED = ToolContract()


def queue_with(*specs):
    """Build a queue holding actions; each spec is (tool, contract, apply_fn)."""
    queue = ApprovalQueue()
    for tool, contract, apply_fn in specs:
        queue.submit(tool=tool, arguments={}, contract=contract, apply_fn=apply_fn)
    return queue


class TestSubmission:
    def test_submitted_action_is_pending(self) -> None:
        queue = ApprovalQueue()
        action = queue.submit(tool="slack", arguments={"channel": "#eng"})
        assert action.is_pending
        assert queue.pending() == [action]
        assert len(queue) == 1

    def test_ids_count_up_and_order_is_submission_order(self) -> None:
        queue = ApprovalQueue()
        ids = [queue.submit(tool="slack", arguments={}).id for _ in range(3)]
        assert ids == [1, 2, 3]
        assert [a.id for a in queue.pending()] == [1, 2, 3]

    def test_title_uses_the_narrator_voice(self) -> None:
        queue = ApprovalQueue()
        action = queue.submit(tool="bash", arguments={"command": "rm -rf dist"})
        assert action.title == "Ran rm -rf dist"

    def test_description_lists_the_arguments(self) -> None:
        queue = ApprovalQueue()
        action = queue.submit(tool="slack", arguments={"channel": "#eng"})
        assert "#eng" in action.description and "slack" in action.description

    def test_long_arguments_are_fenced_and_truncated(self) -> None:
        queue = ApprovalQueue()
        action = queue.submit(tool="bash", arguments={"command": "x" * 5000})
        assert "```" in action.description
        assert len(action.description) < 3000

    def test_contract_is_resolved_when_not_supplied(self) -> None:
        queue = ApprovalQueue()
        assert queue.submit(tool="slack", arguments={}).tag == "comms.send"

    def test_change_subscriber_fires(self) -> None:
        seen = []
        queue = ApprovalQueue(on_change=seen.append)
        action = queue.submit(tool="slack", arguments={})
        queue.approve(action.id, by="rahul")
        assert len(seen) == 2

    def test_a_broken_subscriber_cannot_break_the_queue(self) -> None:
        def boom(_action):
            raise RuntimeError("subscriber exploded")

        queue = ApprovalQueue(on_change=boom)
        assert queue.submit(tool="slack", arguments={}).is_pending


class TestDeferralNotice:
    def test_the_model_is_told_the_truth(self) -> None:
        queue = ApprovalQueue()
        notice = queue.submit(tool="slack", arguments={}).deferral_notice()
        assert "has NOT run" in notice
        assert "Do not retry" in notice
        # Never a fabricated result.
        assert "success" not in notice.lower() or "will succeed" in notice


class TestDecisions:
    def test_approve_applies_the_call(self) -> None:
        applied = []
        queue = queue_with(("slack", AUTO_OK, lambda: applied.append("ran") or "sent"))
        action = queue.approve(1, by="rahul")
        assert applied == ["ran"]
        assert action.state is ActionState.APPROVED
        assert action.result == "sent"
        assert action.resolved_by == "rahul"
        assert not action.auto_approved

    def test_deny_never_applies(self) -> None:
        applied = []
        queue = queue_with(("slack", AUTO_OK, lambda: applied.append("ran")))
        action = queue.deny(1, by="rahul", reason="wrong channel")
        assert applied == []
        assert action.state is ActionState.REJECTED
        assert action.error == "wrong channel"

    def test_deciding_twice_is_a_no_op(self) -> None:
        applied = []
        queue = queue_with(("slack", AUTO_OK, lambda: applied.append("ran")))
        queue.approve(1)
        queue.approve(1)
        queue.deny(1)
        assert applied == ["ran"]
        assert queue.get(1).state is ActionState.APPROVED

    def test_a_failing_apply_marks_failed_and_reraises(self) -> None:
        def boom():
            raise RuntimeError("network down")

        queue = queue_with(("slack", AUTO_OK, boom))
        with pytest.raises(RuntimeError, match="network down"):
            queue.approve(1)
        action = queue.get(1)
        assert action.state is ActionState.FAILED
        assert action.error == "network down"
        assert not action.is_pending

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError):
            ApprovalQueue().approve(99)

    def test_approve_all_applies_in_order(self) -> None:
        order = []
        queue = queue_with(
            *[("slack", AUTO_OK, lambda i=i: order.append(i)) for i in range(3)]
        )
        queue.approve_all(by="rahul")
        assert order == [0, 1, 2]
        assert queue.pending() == []

    def test_approve_all_stops_at_the_first_failure(self) -> None:
        order = []

        def boom():
            raise RuntimeError("nope")

        queue = queue_with(
            ("slack", AUTO_OK, lambda: order.append(0)),
            ("slack", AUTO_OK, boom),
            ("slack", AUTO_OK, lambda: order.append(2)),
        )
        queue.approve_all()
        # The third never ran — a later effect must not land on a broken one.
        assert order == [0]
        assert queue.get(3).is_pending

    def test_deny_all(self) -> None:
        queue = queue_with(*[("slack", AUTO_OK, lambda: None) for _ in range(3)])
        queue.deny_all(reason="not now")
        assert queue.pending() == []
        assert all(a.state is ActionState.REJECTED for a in queue.all())


class TestAutoApproval:
    def test_both_signals_are_required(self) -> None:
        queue = queue_with(("slack", AUTO_OK, lambda: None))
        # Contract says auto-approvable, but no rule is enabled.
        assert queue.drain(by="auto") == []
        assert queue.get(1).is_pending

        queue.enable_auto(SEND, by="rahul")
        assert len(queue.drain(by="auto")) == 1
        assert queue.get(1).state is ActionState.APPROVED

    def test_rule_without_the_contract_verdict_does_nothing(self) -> None:
        not_auto = ToolContract(action_kind=SEND)  # auto_approvable defaults False
        queue = queue_with(("slack", not_auto, lambda: None))
        queue.enable_auto(SEND, by="rahul")
        assert queue.drain(by="auto") == []

    def test_untagged_action_can_never_be_auto_approved(self) -> None:
        queue = queue_with(("mystery", UNTAGGED, lambda: None))
        queue.enable_auto("comms.send", by="rahul")
        assert queue.drain(by="auto") == []

    def test_auto_approval_is_attributed_to_the_rule_enabler(self) -> None:
        queue = queue_with(("slack", AUTO_OK, lambda: None))
        queue.enable_auto(SEND, by="rahul")
        queue.drain(by="the-agent")
        action = queue.get(1)
        assert action.resolved_by == "rahul"  # not "the-agent"
        assert action.auto_approved

    def test_drain_stops_at_the_first_manual_gate(self) -> None:
        order = []
        queue = queue_with(
            ("slack", AUTO_OK, lambda: order.append("first")),
            ("deploy", MANUAL, lambda: order.append("gate")),
            ("slack", AUTO_OK, lambda: order.append("third")),
        )
        queue.enable_auto(SEND, by="rahul")
        queue.drain(by="auto")
        # The third is eligible but sits behind a manual gate — never skipped.
        assert order == ["first"]
        assert queue.get(2).is_pending and queue.get(3).is_pending

    def test_drain_resumes_once_the_gate_is_cleared(self) -> None:
        order = []
        queue = queue_with(
            ("deploy", MANUAL, lambda: order.append("gate")),
            ("slack", AUTO_OK, lambda: order.append("after")),
        )
        queue.enable_auto(SEND, by="rahul")
        assert queue.drain(by="auto") == []
        queue.approve(1, by="rahul")
        queue.drain(by="auto")
        assert order == ["gate", "after"]

    def test_destructive_is_never_auto_approved(self) -> None:
        # Belt and braces: the contract forbids the combination, and the
        # eligibility check refuses it independently.
        destructive = ToolContract(action_kind=SEND, destructive=True)
        queue = queue_with(("rm", destructive, lambda: None))
        queue.enable_auto(SEND, by="rahul")
        assert queue.drain(by="auto") == []

    def test_a_failing_auto_apply_stops_the_drain(self) -> None:
        order = []

        def boom():
            raise RuntimeError("nope")

        queue = queue_with(
            ("slack", AUTO_OK, boom),
            ("slack", AUTO_OK, lambda: order.append("second")),
        )
        queue.enable_auto(SEND, by="rahul")
        queue.drain(by="auto")
        assert order == []
        assert queue.get(2).is_pending

    def test_disable_auto(self) -> None:
        queue = queue_with(("slack", AUTO_OK, lambda: None))
        queue.enable_auto(SEND, by="rahul")
        queue.disable_auto(SEND)
        assert queue.drain(by="auto") == []

    def test_rules_are_listed_with_their_labels(self) -> None:
        queue = ApprovalQueue()
        queue.enable_auto(SEND, by="rahul")
        rule = queue.rules()[0]
        assert rule.tag == "comms.send"
        assert rule.label == "Send a message on your behalf"
        assert rule.enabled_by == "rahul"

    def test_enable_auto_accepts_a_bare_tag(self) -> None:
        queue = ApprovalQueue()
        queue.enable_auto("comms.send", by="rahul")
        assert queue.auto_tags() == {"comms.send"}


class TestConcurrency:
    def test_concurrent_drains_never_double_apply(self) -> None:
        applied: list[int] = []
        lock = threading.Lock()

        def record(i):
            def apply():
                with lock:
                    applied.append(i)

            return apply

        queue = queue_with(*[("slack", AUTO_OK, record(i)) for i in range(20)])
        queue.enable_auto(SEND, by="rahul")

        threads = [threading.Thread(target=lambda: queue.drain(by="auto")) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(applied) == list(range(20))
        assert len(applied) == 20  # each applied exactly once
        assert queue.pending() == []

    def test_concurrent_submit_and_drain(self) -> None:
        queue = ApprovalQueue()
        queue.enable_auto(SEND, by="rahul")
        done = threading.Event()

        def submitter():
            for _ in range(50):
                queue.submit(
                    tool="slack", arguments={}, contract=AUTO_OK, apply_fn=lambda: None
                )
            done.set()

        thread = threading.Thread(target=submitter)
        thread.start()
        while not done.is_set():
            queue.drain(by="auto")
        thread.join()
        queue.drain(by="auto")
        assert queue.pending() == []
        assert len(queue.all()) == 50


class TestBlocking:
    def test_await_decision_actions_are_listed_as_blocking(self) -> None:
        queue = queue_with(
            ("slack", AUTO_OK, lambda: None), ("deploy", MANUAL, lambda: None)
        )
        assert [a.tool for a in queue.blocking()] == ["deploy"]


class TestCoercion:
    def test_none_and_false_give_no_queue(self) -> None:
        assert coerce_queue(None) is None
        assert coerce_queue(False) is None

    def test_true_builds_a_queue(self) -> None:
        assert isinstance(coerce_queue(True), ApprovalQueue)

    def test_a_queue_passes_through(self) -> None:
        queue = ApprovalQueue()
        assert coerce_queue(queue) is queue

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            coerce_queue("yes please")


class TestSummary:
    def test_summary_counts_states(self) -> None:
        queue = queue_with(*[("slack", AUTO_OK, lambda: None) for _ in range(3)])
        queue.approve(1)
        queue.deny(2)
        summary = queue.summary()
        assert summary["total"] == 3
        assert summary["pending"] == 1
        assert summary["counts"]["approved"] == 1
        assert summary["counts"]["rejected"] == 1

    def test_to_dict_is_serializable(self) -> None:
        import json

        queue = ApprovalQueue()
        action = queue.submit(tool="slack", arguments={"channel": "#eng"})
        assert json.dumps(action.to_dict())


class TestRuntimeIntegration:
    """The point of the whole thing: the agent does not stop."""

    @staticmethod
    def _agent(queue, script, tools=None):
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall
        from shipit_agent.permissions import PermissionEngine

        class ScriptedLLM:
            model = "test-model"

            def __init__(self):
                self.n = 0

            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, text_delta_callback=None):
                step = script[self.n] if self.n < len(script) else ("done", [])
                self.n += 1
                text, calls = step
                return LLMResponse(
                    content=text,
                    tool_calls=[ToolCall(name=n, arguments=a) for n, a in calls],
                )

        return Agent(
            llm=ScriptedLLM(),
            tools=tools or [],
            approvals=queue,
            permissions=PermissionEngine(ask=["*"]),
            max_iterations=4,
            # Skill-injected builtins override explicit tools by name
            # (documented last-write-wins), which would silently replace the
            # recording fakes below with the real read_file/bash.
            auto_use_skills=False,
        )

    @staticmethod
    def _tool(name, output="ok", calls=None):
        from shipit_agent.tools.base import ToolOutput

        class Recorded:
            def __init__(self):
                self.name = name
                self.description = name
                self.prompt_instructions = ""

            def schema(self):
                return {"type": "function", "function": {"name": name, "parameters": {}}}

            def run(self, context, **kwargs):
                if calls is not None:
                    calls.append(kwargs)
                return ToolOutput(text=output)

        return Recorded()

    def test_deferrable_action_is_queued_and_the_run_continues(self) -> None:
        ran: list = []
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[
                ("", [("slack", {"channel": "#eng", "text": "shipping"})]),
                ("Told the team.", []),
            ],
            tools=[self._tool("slack", calls=ran)],
        )
        result = agent.run("Tell the team we shipped.")

        # The tool did NOT run, the run completed anyway.
        assert ran == []
        assert result.output == "Told the team."
        assert len(queue.pending()) == 1
        assert queue.pending()[0].tool == "slack"

    def test_the_model_is_told_it_was_queued(self) -> None:
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("slack", {"channel": "#eng"})]), ("ok", [])],
            tools=[self._tool("slack")],
        )
        result = agent.run("Tell the team.")
        tool_messages = [m for m in result.messages if m.role == "tool"]
        assert "has NOT run" in tool_messages[0].content
        assert tool_messages[0].metadata["queued"] is True

    def test_approving_afterwards_actually_runs_it(self) -> None:
        ran: list = []
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("slack", {"channel": "#eng"})]), ("ok", [])],
            tools=[self._tool("slack", calls=ran)],
        )
        agent.run("Tell the team.")
        assert ran == []

        queue.approve_all(by="rahul")
        assert ran == [{"channel": "#eng"}]

    def test_await_decision_tools_still_block(self) -> None:
        ran: list = []
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("bash", {"command": "ls"})]), ("ok", [])],
            tools=[self._tool("bash", calls=ran)],
        )
        result = agent.run("List the files.")
        # bash declares await_decision -> never queued, blocked as before.
        assert queue.pending() == []
        assert ran == []
        tool_messages = [m for m in result.messages if m.role == "tool"]
        assert "requires human approval" in tool_messages[0].content

    def test_an_enabled_rule_applies_during_the_run(self) -> None:
        ran: list = []
        queue = ApprovalQueue()
        queue.enable_auto(SEND, by="rahul")
        agent = self._agent(
            queue,
            script=[("", [("slack", {"channel": "#eng"})]), ("ok", [])],
            tools=[self._tool("slack", output="posted", calls=ran)],
        )
        result = agent.run("Tell the team.")

        assert ran == [{"channel": "#eng"}]      # ran immediately
        assert queue.pending() == []
        tool_messages = [m for m in result.messages if m.role == "tool"]
        assert tool_messages[0].content == "posted"   # real output, not a notice
        assert tool_messages[0].metadata["auto_approved"] is True

    def test_queueing_emits_an_event(self) -> None:
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("slack", {"channel": "#eng"})]), ("ok", [])],
            tools=[self._tool("slack")],
        )
        result = agent.run("Tell the team.")
        queued = [e for e in result.events if e.type == "action_queued"]
        assert len(queued) == 1
        assert queued[0].payload["tool"] == "slack"
        assert queued[0].payload["tag"] == "comms.send"

    def test_without_a_queue_behaviour_is_unchanged(self) -> None:
        ran: list = []
        agent = self._agent(
            None,
            script=[("", [("slack", {"channel": "#eng"})]), ("ok", [])],
            tools=[self._tool("slack", calls=ran)],
        )
        result = agent.run("Tell the team.")
        assert ran == []
        tool_messages = [m for m in result.messages if m.role == "tool"]
        assert "requires human approval" in tool_messages[0].content

    def test_observations_are_never_queued(self) -> None:
        """A read that the policy lets through runs; it never enters the queue.

        The contract decides *queue vs block*, not *gate vs no gate* — a policy
        that says ``ask=["*"]`` still gates reads, and rightly so.
        """
        ran: list = []
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("read_file", {"path": "a.py"})]), ("ok", [])],
            tools=[self._tool("read_file", output="contents", calls=ran)],
        )
        # Only the action is gated; the read is allowed by policy.
        from shipit_agent.permissions import PermissionEngine

        agent.permissions = PermissionEngine(ask=["slack"], allow=["read_file"])
        result = agent.run("Read it.")
        assert ran == [{"path": "a.py"}]
        assert queue.pending() == []
        assert [m for m in result.messages if m.role == "tool"][0].content == "contents"

    def test_a_gated_observation_blocks_rather_than_queueing(self) -> None:
        # An observation has no effect to defer, so "later" is meaningless —
        # the agent needs the data now or not at all.
        queue = ApprovalQueue()
        agent = self._agent(
            queue,
            script=[("", [("read_file", {"path": "a.py"})]), ("ok", [])],
            tools=[self._tool("read_file", output="contents")],
        )
        result = agent.run("Read it.")
        assert queue.pending() == []
        assert "requires human approval" in [
            m for m in result.messages if m.role == "tool"
        ][0].content
