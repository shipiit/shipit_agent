from shipit_agent.context_tracker import ContextTracker
from shipit_agent.models import Message


def test_snapshot_basic():
    tracker = ContextTracker(max_tokens=100_000)
    messages = [
        Message(role="user", content="Hello " * 100),
        Message(role="assistant", content="World " * 200),
    ]
    snap = tracker.snapshot(messages=messages, system_prompt="You are helpful.")
    assert snap.total_tokens > 0
    assert snap.max_tokens == 100_000
    assert 0.0 < snap.utilization < 1.0
    assert "system_prompt" in snap.breakdown
    assert "conversation" in snap.breakdown
    assert snap.will_compact is False


def test_snapshot_compaction_warning():
    tracker = ContextTracker(max_tokens=100, compaction_threshold=0.5)
    messages = [Message(role="user", content="x" * 400)]
    snap = tracker.snapshot(messages=messages)
    assert snap.will_compact is True
    assert snap.utilization >= 0.5


def test_snapshot_to_dict():
    tracker = ContextTracker(max_tokens=1000)
    snap = tracker.snapshot(messages=[], system_prompt="hi")
    data = snap.to_dict()
    assert "total_tokens" in data
    assert "breakdown" in data
    assert "utilization" in data
    assert isinstance(data["utilization"], float)


def test_to_event():
    tracker = ContextTracker(max_tokens=1000)
    tracker.snapshot(messages=[Message(role="user", content="test")])
    event = tracker.to_event()
    assert event.type == "context_snapshot"
    assert "tokens" in event.message
    assert "total_tokens" in event.payload


def test_empty_snapshot():
    tracker = ContextTracker()
    snap = tracker.snapshot(messages=[])
    assert snap.total_tokens == 0
    assert snap.utilization == 0.0
    assert snap.will_compact is False


def test_tool_results_counted_separately():
    tracker = ContextTracker(max_tokens=100_000)
    messages = [
        Message(role="user", content="search for x"),
        Message(role="tool", content="result data " * 500),
    ]
    snap = tracker.snapshot(messages=messages)
    assert snap.breakdown["tool_results"] > snap.breakdown["conversation"]
