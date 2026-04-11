from shipit_agent import (
    Agent,
    AgentChatSession,
    event_packet,
    result_packet,
    sse_event_packet,
    websocket_event_packet,
)
from shipit_agent.llms import SimpleEchoLLM


def test_chat_session_persists_history_across_messages() -> None:
    agent = Agent(llm=SimpleEchoLLM())
    session = AgentChatSession(agent=agent, session_id="chat-1")
    session.send("hello")
    session.send("world")
    history = session.history()
    assert any(
        message.role == "user" and message.content == "hello" for message in history
    )
    assert any(
        message.role == "user" and message.content == "world" for message in history
    )


def test_chat_session_packet_callbacks_receive_packets() -> None:
    seen = []
    agent = Agent(llm=SimpleEchoLLM())
    session = agent.chat_session(session_id="chat-2")
    session.add_packet_callback(seen.append)
    session.send("hello")
    assert seen
    assert seen[0]["packet_type"] == "agent_event"


def test_packet_helpers_return_expected_shapes() -> None:
    agent = Agent(llm=SimpleEchoLLM())
    result = agent.run("hello")
    first_event = result.events[0]
    assert event_packet(first_event)["event"]["type"] == "run_started"
    assert websocket_event_packet(first_event)["type"] == "agent_event"
    assert sse_event_packet(first_event).startswith("event: run_started")
    assert result_packet(result)["result"]["output"]
