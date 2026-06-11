from pathlib import Path
from urllib.parse import urlparse

from shipit_agent import (
    Agent,
    FileOAuthStateStore,
    FileTraceStore,
    GoogleOAuthHelper,
    InMemoryTraceStore,
    Message,
    SlackOAuthHelper,
)
from shipit_agent.llms import SimpleEchoLLM


def test_google_oauth_helper_builds_authorization_url(tmp_path: Path) -> None:
    helper = GoogleOAuthHelper(
        client_id="google-client",
        client_secret="google-secret",
        redirect_uri="https://example.com/oauth/google/callback",
        scopes=["openid", "email"],
        state_store=FileOAuthStateStore(tmp_path / "oauth-state.json"),
    )
    result = helper.create_authorization_url(state_payload={"provider": "google"})
    assert urlparse(result["url"]).netloc == "accounts.google.com"
    assert "scope=openid+email" in result["url"]
    assert helper.state_store.load(result["state"]) == {"provider": "google"}


def test_slack_oauth_helper_builds_authorization_url() -> None:
    helper = SlackOAuthHelper(
        client_id="slack-client",
        client_secret="slack-secret",
        redirect_uri="https://example.com/oauth/slack/callback",
        scopes=["chat:write", "channels:read"],
    )
    result = helper.create_authorization_url()
    assert "slack.com/oauth/v2/authorize" in result["url"]
    assert "chat%3Awrite" in result["url"]


def test_runtime_writes_events_to_trace_store() -> None:
    trace_store = InMemoryTraceStore()
    agent = Agent(llm=SimpleEchoLLM(), trace_store=trace_store, trace_id="trace-1")
    agent.run("hello")
    trace = trace_store.load("trace-1")
    assert trace is not None
    assert any(event.type == "run_started" for event in trace.events)
    assert any(event.type == "run_completed" for event in trace.events)


def test_file_trace_store_persists_events(tmp_path: Path) -> None:
    trace_store = FileTraceStore(tmp_path / "traces")
    agent = Agent(llm=SimpleEchoLLM(), trace_store=trace_store, trace_id="trace-file")
    agent.run("hello")
    trace = trace_store.load("trace-file")
    assert trace is not None
    assert trace.trace_id == "trace-file"
    assert trace.events


def test_trace_store_works_with_seed_history() -> None:
    trace_store = InMemoryTraceStore()
    agent = Agent(
        llm=SimpleEchoLLM(),
        trace_store=trace_store,
        trace_id="trace-history",
        history=[Message(role="user", content="Earlier message")],
    )
    result = agent.run("new")
    # Exactly one system message, and it comes first (providers expect a single
    # leading system message); seed history is preserved right after it.
    system_messages = [m for m in result.messages if m.role == "system"]
    assert len(system_messages) == 1
    assert result.messages[0].role == "system"
    assert any(m.content == "Earlier message" for m in result.messages)
    trace = trace_store.load("trace-history")
    assert trace is not None
    assert len(trace.events) >= 2
