from dataclasses import dataclass, field

from shipit_agent.schedule import ScheduleResult, ScheduleRunner


@dataclass
class FakeResult:
    output: str = "done"
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    metadata: dict = field(
        default_factory=lambda: {"usage": {"input": 100, "output": 50}}
    )
    parsed: object = None


@dataclass
class FakeChatSession:
    session_id: str = "s1"

    def send(self, prompt):
        return FakeResult(output=f"session reply to: {prompt}")


@dataclass
class FakeAgent:
    _result: FakeResult = field(default_factory=FakeResult)
    _chat: FakeChatSession = field(default_factory=FakeChatSession)
    session_store: object = None

    def run(self, prompt):
        return FakeResult(output=f"reply to: {prompt}")

    def chat_session(self, session_id):
        return self._chat


def test_execute_without_session():
    agent = FakeAgent()
    runner = ScheduleRunner(agent=agent)
    result = runner.execute("hello")
    assert isinstance(result, ScheduleResult)
    assert "reply to: hello" in result.agent_result.output


def test_execute_with_session():
    agent = FakeAgent(session_store=object())
    runner = ScheduleRunner(agent=agent)
    result = runner.execute("hello", session_id="s1")
    assert "session reply to: hello" in result.agent_result.output
    assert result.schedule_metadata["session_id"] == "s1"


def test_execute_stream():
    from shipit_agent.models import AgentEvent

    events = [
        AgentEvent(type="run_started", message="start", payload={}),
        AgentEvent(type="run_completed", message="done", payload={}),
    ]

    @dataclass
    class StreamAgent:
        session_store: object = None

        def stream(self, prompt):
            yield from events

    runner = ScheduleRunner(agent=StreamAgent())
    collected = list(runner.execute_stream("test"))
    assert len(collected) == 2
    assert collected[0].type == "run_started"
