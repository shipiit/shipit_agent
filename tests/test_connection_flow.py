"""Asking for a connection, and answering — the flow a UI drives.

The registry knew what was connected; nothing turned "I need Slack" into
something a user could accept or deny. This is that round trip: the agent
asks, the run carries an event a UI can draw a card from, the user answers,
and the next state check reflects the answer.
"""

from __future__ import annotations

from shipit_agent import Agent, ConnectionRegistry
from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import AgentEvent, ToolCall
from shipit_agent.narrate import (
    ConnectionRow,
    build_transcript,
    render_chat_html,
    render_markdown,
    render_tree,
    timeline,
)
from shipit_agent.tools.connections import ConnectionsTool


class Slack:
    name = "slack"
    description = "Post a message to Slack."
    prompt_instructions = ""
    credential_key = "slack"

    def schema(self):
        return {"type": "function", "function": {"name": self.name}}


def registry(**kwargs) -> ConnectionRegistry:
    return ConnectionRegistry(
        credential_store=kwargs.pop("store", InMemoryCredentialStore()),
        tools=[Slack()],
        **kwargs,
    )


class TestAsking:
    def test_a_request_is_recorded_with_its_reason(self) -> None:
        reg = registry()
        request = reg.request("slack", "I need to post the release note.")
        assert request.title == "Slack"
        assert reg.pending_requests() == [request]

    def test_the_tool_refuses_a_request_with_no_reason(self) -> None:
        from shipit_agent.tools.base import ToolContext
        from shipit_agent.tools.connections.connections_tool import (
            REGISTRY_STATE_KEY,
        )

        tool = ConnectionsTool()
        out = tool.run(
            ToolContext(prompt="", state={REGISTRY_STATE_KEY: registry()}),
            action="request",
            connection="slack",
        )
        assert out.metadata["error"] == "missing_reason", (
            "a request with no reason is one the user cannot evaluate"
        )

    def test_asking_for_something_already_connected_says_so(self) -> None:
        from shipit_agent.tools.base import ToolContext
        from shipit_agent.tools.connections.connections_tool import (
            REGISTRY_STATE_KEY,
        )

        store = InMemoryCredentialStore()
        store.set(CredentialRecord(key="slack", provider="slack",
                                   secrets={"token": "x"}))
        tool = ConnectionsTool()
        out = tool.run(
            ToolContext(prompt="", state={REGISTRY_STATE_KEY: registry(store=store)}),
            action="request", connection="slack", reason="post the note",
        )
        assert out.metadata.get("already_connected")


class TestAnswering:
    def test_accepting_with_a_credential_connects_it(self) -> None:
        reg = registry()
        reg.request("slack", "post the note")
        answered = reg.resolve("slack", accepted=True, credential="xoxb-1")
        assert answered is not None and answered.accepted
        assert reg.is_connected("slack")
        assert reg.pending_requests() == []

    def test_a_dict_credential_is_stored_whole(self) -> None:
        store = InMemoryCredentialStore()
        reg = registry(store=store)
        reg.request("slack", "post")
        reg.resolve("slack", accepted=True,
                    credential={"token": "t", "team": "acme"})
        assert store.get("slack").secrets == {"token": "t", "team": "acme"}

    def test_a_credential_record_passes_through(self) -> None:
        store = InMemoryCredentialStore()
        reg = registry(store=store)
        reg.request("slack", "post")
        reg.resolve(
            "slack", accepted=True,
            credential=CredentialRecord(key="slack", provider="slack",
                                        secrets={"token": "t"}),
        )
        assert store.get("slack").secrets["token"] == "t"

    def test_denying_closes_the_request_without_connecting(self) -> None:
        reg = registry()
        reg.request("slack", "post the note")
        answered = reg.resolve("slack", accepted=False)
        assert answered is not None and not answered.accepted
        assert reg.pending_requests() == []
        assert not reg.is_connected("slack"), "a denial must not connect anything"

    def test_answering_a_request_that_was_never_made(self) -> None:
        assert registry().resolve("slack", accepted=True) is None

    def test_who_answered_is_recorded(self) -> None:
        reg = registry()
        reg.request("slack", "post")
        assert reg.resolve("slack", accepted=True, by="rahul").resolved_by == "rahul"


class TestTheRunCarriesIt:
    """A UI cannot draw a card it never hears about."""

    def _agent(self, tool_output: str = "requested"):
        class L:
            model = "m"

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[ToolCall(
                            name="connections",
                            arguments={"action": "request",
                                       "connection": "slack",
                                       "reason": "post the release note"},
                        )],
                        usage={},
                    )
                return LLMResponse(content="Asked you to connect Slack.", usage={})

        return Agent(llm=L(), tools=[ConnectionsTool(), Slack()],
                     auto_use_skills=False, max_iterations=3)

    def test_the_sync_loop_emits_the_event(self) -> None:
        events = list(self._agent().stream("Post the release note to #eng."))
        requests = [e for e in events if e.type == "connection_requested"]
        assert requests, "the run must carry the request, not only the tool text"
        payload = requests[0].payload
        assert payload["connection_id"] == "slack"
        assert payload["reason"] == "post the release note"
        assert payload["auth"]

    def test_a_normal_tool_result_emits_nothing(self) -> None:
        class Quiet:
            name = "noop"
            description = "Does nothing."
            prompt_instructions = ""

            def schema(self):
                return {"type": "function", "function": {"name": self.name}}

            def run(self, context, **kwargs):
                from shipit_agent.tools.base import ToolOutput

                return ToolOutput(text="fine")

        class L:
            model = "m"

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[ToolCall(name="noop", arguments={})],
                        usage={},
                    )
                return LLMResponse(content="done", usage={})

        agent = Agent(llm=L(), tools=[Quiet()], auto_use_skills=False,
                      max_iterations=3)
        events = list(agent.stream("do nothing"))
        assert not [e for e in events if e.type == "connection_requested"]


REQUEST = AgentEvent(
    type="connection_requested",
    message="",
    payload={
        "connection_id": "bigquery",
        "title": "BigQuery — analytics.usage",
        "reason": "Read the usage tables",
        "auth": "oauth",
        "tool": "connections",
    },
)
DONE = AgentEvent(type="run_completed", message="",
                  payload={"output": "Waiting on you.", "usage": {}})


class TestItRendersEverywhere:
    def test_the_transcript_gets_a_row_of_its_own(self) -> None:
        rows = build_transcript([REQUEST, DONE])
        assert any(isinstance(row, ConnectionRow) for row in rows)

    def test_the_panel_draws_a_card_with_the_reason(self) -> None:
        page = render_chat_html([REQUEST, DONE])
        assert "sa-connect" in page
        assert "Read the usage tables" in page      # why, not just what
        assert "Connect" in page and "Not now" in page

    def test_oauth_says_sign_in_rather_than_paste_a_key(self) -> None:
        page = render_chat_html([REQUEST, DONE])
        assert "sign in" in page

    def test_the_tree_names_it(self) -> None:
        out = render_tree([REQUEST, DONE])
        assert "Connection needed" in out
        assert "BigQuery" in out and "Read the usage tables" in out

    def test_the_timeline_emits_a_step_a_frontend_can_switch_on(self) -> None:
        steps = timeline([REQUEST, DONE])
        card = next(s for s in steps if s["type"] == "connection_required")
        assert card["connection_id"] == "bigquery"
        assert card["auth"] == "oauth"

    def test_the_report_has_a_section(self) -> None:
        assert "Connection required" in render_markdown([REQUEST, DONE])

    def test_it_interrupts_the_work_run_like_an_approval_does(self) -> None:
        events = [
            AgentEvent(type="tool_called", message="",
                       payload={"tool": "read_file", "call_id": "1",
                                "arguments": {"path": "a.py"}}),
            AgentEvent(type="tool_completed", message="",
                       payload={"tool": "read_file", "call_id": "1",
                                "output": "x"}),
            REQUEST,
            DONE,
        ]
        rows = build_transcript(events)
        kinds = [type(row).__name__ for row in rows]
        assert kinds.index("WorkRow") < kinds.index("ConnectionRow")
