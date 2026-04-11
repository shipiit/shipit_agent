# Advanced Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Scheduled Agent Runs, Webhook Triggers, Session Persistence, and Context Window Visualization across shipit_agent lib, shipit_ui backend, and shipit_ui frontend.

**Architecture:** Agent lib gets 5 new modules (ScheduleRunner, SessionManager, ContextTracker, PromptTemplate, WebhookPayloadTool). Backend gets 3 new Django apps (schedules, webhooks, sessions) + Celery integration. Frontend gets 3 new feature directories + ContextWindowBar component + sidebar/router updates.

**Tech Stack:** Python 3.11, Django 5 + DRF, Celery + django-celery-beat + Redis, React 18 + TypeScript + Tailwind CSS, SSE for streaming.

---

## File Structure

### shipit_agent lib (new files)
- `shipit_agent/templates.py` — PromptTemplate for {variable} rendering
- `shipit_agent/context_tracker.py` — ContextTracker + ContextSnapshot
- `shipit_agent/schedule.py` — ScheduleRunner + ScheduleResult
- `shipit_agent/session_manager.py` — SessionManager with create/resume/fork/archive
- `shipit_agent/tools/webhook_payload.py` — WebhookPayloadTool

### shipit_agent lib (modified files)
- `shipit_agent/models.py` — Add `context_snapshot` to EventType
- `shipit_agent/stores/session.py` — Add `list_all()` to session stores
- `shipit_agent/__init__.py` — Export new public API

### shipit_ui backend (new apps)
- `backend/apps/sessions/` — models, serializers, views, urls, __init__, apps
- `backend/apps/schedules/` — models, serializers, views, urls, tasks, __init__, apps
- `backend/apps/webhooks/` — models, serializers, views, urls, tasks, __init__, apps

### shipit_ui backend (modified files)
- `backend/shipit_cloud/settings.py` — Add new apps to INSTALLED_APPS, add Celery config
- `backend/shipit_cloud/urls.py` — Add URL patterns for new apps
- `backend/shipit_cloud/celery.py` — NEW: Celery app configuration

### shipit_ui frontend (new files)
- `frontend/src/types/session.ts` — Session + SessionMessage types
- `frontend/src/types/schedule.ts` — Schedule + ScheduleRun types
- `frontend/src/types/webhook.ts` — Webhook + WebhookDelivery types
- `frontend/src/types/context.ts` — ContextSnapshot type
- `frontend/src/api/sessions.ts` — Session API client
- `frontend/src/api/schedules.ts` — Schedule API client
- `frontend/src/api/webhooks.ts` — Webhook API client
- `frontend/src/components/shared/ContextWindowBar.tsx` — Reusable context viz
- `frontend/src/features/sessions/SessionListPage.tsx`
- `frontend/src/features/sessions/SessionChatPage.tsx`
- `frontend/src/features/schedules/ScheduleListPage.tsx`
- `frontend/src/features/schedules/ScheduleBuilderPage.tsx`
- `frontend/src/features/schedules/ScheduleDetailPage.tsx`
- `frontend/src/features/webhooks/WebhookListPage.tsx`
- `frontend/src/features/webhooks/WebhookBuilderPage.tsx`
- `frontend/src/features/webhooks/WebhookDetailPage.tsx`

### shipit_ui frontend (modified files)
- `frontend/src/router.tsx` — Add new routes
- `frontend/src/components/layout/AppShell.tsx` — Add sidebar nav items

---

## Task 1: Agent Lib — PromptTemplate

**Files:**
- Create: `shipit_agent/templates.py`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_templates.py`:

```python
from shipit_agent.templates import PromptTemplate


def test_render_simple_variable():
    t = PromptTemplate(template="Hello {name}")
    assert t.render(name="World") == "Hello World"


def test_render_nested_variable():
    t = PromptTemplate(template="Review PR: {payload.pull_request.title}")
    payload = {"pull_request": {"title": "Fix auth bug"}}
    assert t.render(payload=payload) == "Review PR: Fix auth bug"


def test_render_missing_variable_unchanged():
    t = PromptTemplate(template="Hello {missing}")
    assert t.render(name="World") == "Hello {missing}"


def test_variables_extraction():
    t = PromptTemplate(template="Check {payload.repo} for {payload.event}")
    assert t.variables() == ["payload.repo", "payload.event"]


def test_render_multiple_variables():
    t = PromptTemplate(template="{payload.action} on {payload.repo.name} by {payload.sender.login}")
    payload = {"action": "opened", "repo": {"name": "shipit"}, "sender": {"login": "rahul"}}
    assert t.render(payload=payload) == "opened on shipit by rahul"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_templates.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

Create `shipit_agent/templates.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PromptTemplate:
    """Renders prompt templates with {variable.path} references.

    Supports nested dot-path access: {payload.pull_request.title}
    resolves to payload["pull_request"]["title"].
    """

    template: str

    def render(self, **context: Any) -> str:
        def _replacer(match: re.Match[str]) -> str:
            path = match.group(1)
            parts = path.split(".")
            value: Any = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, match.group(0))
                    if value is match.group(0):
                        return value
                else:
                    return match.group(0)
            return str(value)

        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", _replacer, self.template)

    def variables(self) -> list[str]:
        return re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", self.template)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_templates.py -v`
Expected: All 5 tests PASS

---

## Task 2: Agent Lib — ContextTracker + ContextSnapshot

**Files:**
- Create: `shipit_agent/context_tracker.py`
- Modify: `shipit_agent/models.py` — add `context_snapshot` to EventType
- Test: `tests/test_context_tracker.py`

- [ ] **Step 1: Add context_snapshot to EventType**

In `shipit_agent/models.py`, add `"context_snapshot"` to the EventType Literal:

```python
EventType = Literal[
    "run_started",
    "reasoning_started",
    "reasoning_completed",
    "step_started",
    "planning_started",
    "planning_completed",
    "tool_called",
    "tool_completed",
    "tool_failed",
    "interactive_request",
    "mcp_attached",
    "llm_retry",
    "tool_retry",
    "run_completed",
    "context_snapshot",
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_context_tracker.py`:

```python
from shipit_agent.context_tracker import ContextSnapshot, ContextTracker
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
    d = snap.to_dict()
    assert "total_tokens" in d
    assert "breakdown" in d
    assert "utilization" in d
    assert isinstance(d["utilization"], float)


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_context_tracker.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: Write implementation**

Create `shipit_agent/context_tracker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import AgentEvent, Message


@dataclass(slots=True)
class ContextSnapshot:
    """Point-in-time snapshot of context window utilization."""

    total_tokens: int
    max_tokens: int
    breakdown: dict[str, int]
    utilization: float
    compaction_threshold: float
    will_compact: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "breakdown": self.breakdown,
            "utilization": round(self.utilization, 4),
            "compaction_threshold": self.compaction_threshold,
            "will_compact": self.will_compact,
        }


@dataclass(slots=True)
class ContextTracker:
    """Tracks context window utilization across agent execution.

    Estimates token counts for each category of context content and
    produces snapshots for UI visualization.
    """

    max_tokens: int = 128_000
    compaction_threshold: float = 0.75
    snapshots: list[ContextSnapshot] = field(default_factory=list)

    def snapshot(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
        memory_context: str = "",
        system_prompt: str = "",
    ) -> ContextSnapshot:
        breakdown = {
            "system_prompt": self._estimate_tokens(system_prompt),
            "conversation": sum(
                self._estimate_tokens(m.content)
                for m in messages
                if m.role not in ("system", "tool")
            ),
            "tool_schemas": sum(
                self._estimate_tokens(str(s)) for s in (tool_schemas or [])
            ),
            "tool_results": sum(
                self._estimate_tokens(m.content) for m in messages if m.role == "tool"
            ),
            "memory": self._estimate_tokens(memory_context),
        }

        total = sum(breakdown.values())
        utilization = total / self.max_tokens if self.max_tokens > 0 else 0.0

        snap = ContextSnapshot(
            total_tokens=total,
            max_tokens=self.max_tokens,
            breakdown=breakdown,
            utilization=utilization,
            compaction_threshold=self.compaction_threshold,
            will_compact=utilization >= self.compaction_threshold,
        )
        self.snapshots.append(snap)
        return snap

    def to_event(self) -> AgentEvent:
        if not self.snapshots:
            return AgentEvent(
                type="context_snapshot", message="No snapshots", payload={}
            )
        latest = self.snapshots[-1]
        return AgentEvent(
            type="context_snapshot",
            message=f"Context: {latest.total_tokens}/{latest.max_tokens} tokens ({latest.utilization:.0%})",
            payload=latest.to_dict(),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_context_tracker.py -v`
Expected: All 6 tests PASS

---

## Task 3: Agent Lib — WebhookPayloadTool

**Files:**
- Create: `shipit_agent/tools/webhook_payload.py`
- Test: `tests/test_webhook_payload_tool.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_webhook_payload_tool.py`:

```python
from shipit_agent.tools.webhook_payload import WebhookPayloadTool
from shipit_agent.tools.base import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(prompt="", metadata={}, state={})


def test_full_payload():
    tool = WebhookPayloadTool(payload={"event": "push", "repo": "shipit"})
    output = tool.run(_ctx())
    assert '"event": "push"' in output.text
    assert '"repo": "shipit"' in output.text


def test_nested_path():
    tool = WebhookPayloadTool(
        payload={"pull_request": {"title": "Fix bug", "number": 42}}
    )
    output = tool.run(_ctx(), path="pull_request.title")
    assert output.text == "Fix bug"


def test_numeric_index():
    tool = WebhookPayloadTool(payload={"items": ["a", "b", "c"]})
    output = tool.run(_ctx(), path="items.1")
    assert output.text == "b"


def test_missing_path():
    tool = WebhookPayloadTool(payload={"a": 1})
    output = tool.run(_ctx(), path="b.c.d")
    assert "not found" in output.text


def test_schema():
    tool = WebhookPayloadTool(payload={})
    s = tool.schema()
    assert s["name"] == "webhook_payload"
    assert "path" in s["parameters"]["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_webhook_payload_tool.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write implementation**

Create `shipit_agent/tools/webhook_payload.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .base import ToolContext, ToolOutput


@dataclass(slots=True)
class WebhookPayloadTool:
    """Tool that gives an agent access to the webhook payload that triggered it.

    Pass a dot-separated path to get a nested value (e.g. 'pull_request.title'),
    or pass no path to get the full payload.
    """

    name: str = "webhook_payload"
    description: str = (
        "Access the webhook payload that triggered this agent run. "
        "Pass a dot-separated path to get a nested value, "
        "or no path for the full payload."
    )
    prompt_instructions: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Dot-separated path to a nested value, "
                            "e.g. 'pull_request.title'. Empty for full payload."
                        ),
                    }
                },
            },
        }

    def run(self, context: ToolContext, path: str = "") -> ToolOutput:
        if not path:
            return ToolOutput(
                text=json.dumps(self.payload, indent=2), metadata={}
            )

        value: Any = self.payload
        for key in path.split("."):
            if isinstance(value, dict):
                if key not in value:
                    return ToolOutput(
                        text=f"Path '{path}' not found in payload", metadata={}
                    )
                value = value[key]
            elif isinstance(value, list) and key.isdigit():
                idx = int(key)
                if idx >= len(value):
                    return ToolOutput(
                        text=f"Path '{path}' not found in payload", metadata={}
                    )
                value = value[idx]
            else:
                return ToolOutput(
                    text=f"Path '{path}' not found in payload", metadata={}
                )

        if isinstance(value, (dict, list)):
            return ToolOutput(text=json.dumps(value, indent=2), metadata={})
        return ToolOutput(text=str(value), metadata={})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_webhook_payload_tool.py -v`
Expected: All 5 tests PASS

---

## Task 4: Agent Lib — SessionManager + list_all()

**Files:**
- Create: `shipit_agent/session_manager.py`
- Modify: `shipit_agent/stores/session.py` — add `list_all()` to both stores
- Test: `tests/test_session_manager.py`

- [ ] **Step 1: Add list_all() to session stores**

In `shipit_agent/stores/session.py`, add `list_all()` method to `InMemorySessionStore`:

```python
def list_all(self) -> list[SessionRecord]:
    return list(self._records.values())
```

Add `list_all()` method to `FileSessionStore`:

```python
def list_all(self) -> list[SessionRecord]:
    records: list[SessionRecord] = []
    if not self._root.exists():
        return records
    for path in sorted(self._root.glob("*.json")):
        record = self.load(path.stem)
        if record is not None:
            records.append(record)
    return records
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_session_manager.py`:

```python
from shipit_agent.session_manager import SessionManager
from shipit_agent.stores.session import InMemorySessionStore, SessionRecord


class FakeAgent:
    """Minimal agent stub with chat_session support."""

    def __init__(self, store):
        self.session_store = store
        self._sessions = {}

    def chat_session(self, session_id):
        return _FakeChatSession(session_id, self.session_store)


class _FakeChatSession:
    def __init__(self, session_id, store):
        self.session_id = session_id
        self.store = store


def test_create_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat = mgr.create(agent, name="test session")
    assert chat.session_id is not None
    records = store.list_all()
    assert len(records) == 1
    assert records[0].metadata["name"] == "test session"


def test_resume_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat1 = mgr.create(agent, name="s1")
    chat2 = mgr.resume(agent, chat1.session_id)
    assert chat2.session_id == chat1.session_id


def test_resume_nonexistent_raises():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    try:
        mgr.resume(agent, "nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_list_sessions():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    mgr.create(agent, name="s1")
    mgr.create(agent, name="s2")
    assert len(mgr.list_sessions()) == 2


def test_archive_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat = mgr.create(agent, name="s1")
    mgr.archive(chat.session_id)
    record = store.load(chat.session_id)
    assert record.metadata.get("archived") is True


def test_fork_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)

    # Create and add messages
    chat = mgr.create(agent, name="original")
    record = store.load(chat.session_id)
    from shipit_agent.models import Message
    record.messages = [
        Message(role="user", content="msg1"),
        Message(role="assistant", content="resp1"),
        Message(role="user", content="msg2"),
        Message(role="assistant", content="resp2"),
    ]
    store.save(record)

    # Fork from message 2 (keep first 2 messages)
    forked = mgr.fork(agent, chat.session_id, from_message=2)
    forked_record = store.load(forked.session_id)
    assert len(forked_record.messages) == 2
    assert forked_record.metadata["forked_from"] == chat.session_id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_session_manager.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: Write implementation**

Create `shipit_agent/session_manager.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .stores.session import SessionRecord, SessionStore


@dataclass(slots=True)
class SessionManager:
    """Manages multiple chat sessions with lifecycle control.

    Provides create/resume/list/archive/fork operations over a SessionStore.
    """

    session_store: SessionStore

    def create(
        self, agent: Any, name: str = "", metadata: dict[str, Any] | None = None
    ) -> Any:
        session_id = str(uuid.uuid4())
        record = SessionRecord(
            session_id=session_id,
            messages=[],
            metadata={"name": name, **(metadata or {})},
        )
        self.session_store.save(record)
        return agent.chat_session(session_id)

    def resume(self, agent: Any, session_id: str) -> Any:
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id!r} not found")
        return agent.chat_session(session_id)

    def list_sessions(self) -> list[SessionRecord]:
        if hasattr(self.session_store, "list_all"):
            return self.session_store.list_all()
        return []

    def archive(self, session_id: str) -> None:
        record = self.session_store.load(session_id)
        if record is not None:
            record.metadata["archived"] = True
            self.session_store.save(record)

    def fork(
        self, agent: Any, session_id: str, from_message: int = -1
    ) -> Any:
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id!r} not found")

        new_id = str(uuid.uuid4())
        messages = (
            record.messages[:from_message]
            if from_message > 0
            else record.messages[:]
        )
        new_record = SessionRecord(
            session_id=new_id,
            messages=messages,
            metadata={
                "name": f"Fork of {record.metadata.get('name', session_id)}",
                "forked_from": session_id,
                "forked_at_message": from_message,
            },
        )
        self.session_store.save(new_record)
        return agent.chat_session(new_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_session_manager.py -v`
Expected: All 6 tests PASS

---

## Task 5: Agent Lib — ScheduleRunner

**Files:**
- Create: `shipit_agent/schedule.py`
- Test: `tests/test_schedule_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_schedule_runner.py`:

```python
from dataclasses import dataclass, field

from shipit_agent.schedule import ScheduleResult, ScheduleRunner
from shipit_agent.models import AgentResult


@dataclass
class FakeResult:
    output: str = "done"
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    metadata: dict = field(default_factory=lambda: {"usage": {"input": 100, "output": 50}})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_schedule_runner.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write implementation**

Create `shipit_agent/schedule.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from .models import AgentEvent


@dataclass(slots=True)
class ScheduleResult:
    """Result of a scheduled execution."""

    agent_result: Any
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleRunner:
    """Executes an agent run on behalf of a scheduler.

    Works with any agent type (Agent, GoalAgent, Supervisor, etc.)
    since they all expose .run() and .stream().
    """

    agent: Any

    def execute(self, prompt: str, session_id: str | None = None) -> ScheduleResult:
        if session_id and hasattr(self.agent, "chat_session"):
            chat = self.agent.chat_session(session_id)
            result = chat.send(prompt)
        else:
            result = self.agent.run(prompt)

        usage = getattr(result, "metadata", {}).get("usage", {})
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "session_id": session_id,
                "token_count": sum(usage.values()) if isinstance(usage, dict) else 0,
            },
        )

    def execute_stream(
        self, prompt: str, session_id: str | None = None
    ) -> Iterator[AgentEvent]:
        if session_id and hasattr(self.agent, "chat_session"):
            chat = self.agent.chat_session(session_id)
            yield from chat.stream(prompt)
        else:
            yield from self.agent.stream(prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/test_schedule_runner.py -v`
Expected: All 3 tests PASS

---

## Task 6: Agent Lib — Update __init__.py exports

**Files:**
- Modify: `shipit_agent/__init__.py`

- [ ] **Step 1: Add new exports to __init__.py**

Add these imports to the appropriate sections in `shipit_agent/__init__.py`:

```python
# Templates
from .templates import PromptTemplate

# Context tracking
from .context_tracker import ContextSnapshot, ContextTracker

# Schedule
from .schedule import ScheduleResult, ScheduleRunner

# Session management
from .session_manager import SessionManager

# Webhook tool
from .tools.webhook_payload import WebhookPayloadTool
```

- [ ] **Step 2: Verify all imports work**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -c "from shipit_agent import PromptTemplate, ContextTracker, ContextSnapshot, ScheduleRunner, ScheduleResult, SessionManager, WebhookPayloadTool; print('All exports OK')"`
Expected: "All exports OK"

- [ ] **Step 3: Run full test suite to verify nothing is broken**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

---

## Task 7: Backend — Celery Configuration

**Files:**
- Create: `backend/shipit_cloud/celery.py`
- Modify: `backend/shipit_cloud/__init__.py`
- Modify: `backend/shipit_cloud/settings.py`

- [ ] **Step 1: Create Celery app configuration**

Create `backend/shipit_cloud/celery.py`:

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shipit_cloud.settings")

app = Celery("shipit_cloud")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

- [ ] **Step 2: Load Celery in Django's __init__.py**

In `backend/shipit_cloud/__init__.py`, add:

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

- [ ] **Step 3: Add Celery + new apps to settings.py**

In `backend/shipit_cloud/settings.py`, add to INSTALLED_APPS:

```python
"django_celery_beat",
"apps.sessions",
"apps.schedules",
"apps.webhooks",
```

Add Celery configuration at the end of settings.py:

```python
# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
```

- [ ] **Step 4: Install dependencies**

Run: `cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/backend && pip install celery django-celery-beat redis`

---

## Task 8: Backend — Sessions App

**Files:**
- Create: `backend/apps/sessions/__init__.py`
- Create: `backend/apps/sessions/apps.py`
- Create: `backend/apps/sessions/models.py`
- Create: `backend/apps/sessions/serializers.py`
- Create: `backend/apps/sessions/urls.py`
- Create: `backend/apps/sessions/views/__init__.py`
- Create: `backend/apps/sessions/views/shared.py`
- Create: `backend/apps/sessions/views/list_create.py`
- Create: `backend/apps/sessions/views/detail.py`
- Create: `backend/apps/sessions/views/send.py`
- Create: `backend/apps/sessions/views/stream.py`
- Create: `backend/apps/sessions/views/fork.py`
- Modify: `backend/shipit_cloud/urls.py`

- [ ] **Step 1: Create app boilerplate**

Create `backend/apps/sessions/__init__.py` (empty).

Create `backend/apps/sessions/apps.py`:

```python
from django.apps import AppConfig


class SessionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sessions"
```

- [ ] **Step 2: Create models**

Create `backend/apps/sessions/models.py`:

```python
from django.conf import settings
from django.db import models

from apps.agents.models import AgentConfig
from apps.deep_agents.models import DeepAgent


class AgentSession(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
    )
    name = models.CharField(max_length=200)

    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sessions",
    )
    deep_agent = models.ForeignKey(
        DeepAgent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sessions",
    )

    messages = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    message_count = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)

    forked_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forks",
    )
    forked_at_message = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
```

- [ ] **Step 3: Create serializers**

Create `backend/apps/sessions/serializers.py`:

```python
from rest_framework import serializers

from .models import AgentSession


class AgentSessionSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()
    deep_agent_name = serializers.SerializerMethodField()

    class Meta:
        model = AgentSession
        fields = [
            "id", "name", "agent", "deep_agent", "agent_name", "deep_agent_name",
            "messages", "is_active", "is_archived", "message_count", "token_count",
            "forked_from", "forked_at_message", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "messages", "message_count", "token_count",
            "forked_from", "forked_at_message", "created_at", "updated_at",
        ]

    def get_agent_name(self, obj):
        return obj.agent.name if obj.agent else None

    def get_deep_agent_name(self, obj):
        return obj.deep_agent.name if obj.deep_agent else None


class AgentSessionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — no messages."""

    agent_name = serializers.SerializerMethodField()
    deep_agent_name = serializers.SerializerMethodField()

    class Meta:
        model = AgentSession
        fields = [
            "id", "name", "agent", "deep_agent", "agent_name", "deep_agent_name",
            "is_active", "is_archived", "message_count", "token_count",
            "created_at", "updated_at",
        ]

    def get_agent_name(self, obj):
        return obj.agent.name if obj.agent else None

    def get_deep_agent_name(self, obj):
        return obj.deep_agent.name if obj.deep_agent else None
```

- [ ] **Step 4: Create views — shared.py**

Create `backend/apps/sessions/views/__init__.py`:

```python
from .list_create import SessionListCreateView
from .detail import SessionDetailView
from .send import SessionSendView
from .stream import SessionStreamView
from .fork import SessionForkView, SessionArchiveView
```

Create `backend/apps/sessions/views/shared.py`:

```python
from apps.common.auth import resolve_request_user

from ..models import AgentSession


def get_session_for_request(request, pk: int) -> AgentSession:
    user = resolve_request_user(request)
    return AgentSession.objects.get(owner=user, pk=pk)
```

- [ ] **Step 5: Create views — list_create.py**

Create `backend/apps/sessions/views/list_create.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.auth import resolve_request_user

from ..models import AgentSession
from ..serializers import AgentSessionListSerializer, AgentSessionSerializer


class SessionListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="List sessions",
        responses={200: AgentSessionListSerializer(many=True)},
    )
    def get(self, request):
        user = resolve_request_user(request)
        qs = AgentSession.objects.filter(owner=user)

        agent_id = request.query_params.get("agent_id")
        if agent_id:
            qs = qs.filter(agent_id=agent_id)

        deep_agent_id = request.query_params.get("deep_agent_id")
        if deep_agent_id:
            qs = qs.filter(deep_agent_id=deep_agent_id)

        is_archived = request.query_params.get("is_archived")
        if is_archived is not None:
            qs = qs.filter(is_archived=is_archived.lower() == "true")

        return Response(AgentSessionListSerializer(qs, many=True).data)

    @swagger_auto_schema(
        operation_summary="Create session",
        request_body=AgentSessionSerializer,
        responses={201: AgentSessionSerializer},
    )
    def post(self, request):
        user = resolve_request_user(request)
        serializer = AgentSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 6: Create views — detail.py**

Create `backend/apps/sessions/views/detail.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import AgentSessionSerializer
from .shared import get_session_for_request


class SessionDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Get session",
        responses={200: AgentSessionSerializer},
    )
    def get(self, request, pk: int):
        session = get_session_for_request(request, pk)
        return Response(AgentSessionSerializer(session).data)

    @swagger_auto_schema(
        operation_summary="Update session",
        request_body=AgentSessionSerializer,
        responses={200: AgentSessionSerializer},
    )
    def put(self, request, pk: int):
        session = get_session_for_request(request, pk)
        serializer = AgentSessionSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @swagger_auto_schema(operation_summary="Delete session")
    def delete(self, request, pk: int):
        session = get_session_for_request(request, pk)
        session.delete()
        return Response(status=204)
```

- [ ] **Step 7: Create views — send.py**

Create `backend/apps/sessions/views/send.py`:

```python
import json
from datetime import datetime

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.traces.models import Trace, TraceEvent

from .shared import get_session_for_request


class SessionSendView(APIView):
    """Send a message to a session and get the agent's response."""

    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Send message to session",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"prompt": openapi.Schema(type=openapi.TYPE_STRING)},
        ),
    )
    def post(self, request, pk: int):
        session = get_session_for_request(request, pk)
        prompt = request.data.get("prompt", "")

        if not prompt.strip():
            return Response({"error": "prompt is required"}, status=400)

        # Build mock agent response (real implementation will use shipit_agent)
        now = datetime.utcnow().isoformat()
        user_msg = {"role": "user", "content": prompt, "timestamp": now, "metadata": {}}

        # Simulate agent response — to be replaced with real agent execution
        assistant_content = f"[Session agent response to: {prompt}]"
        token_count = max(1, len(prompt) // 4) + max(1, len(assistant_content) // 4)

        assistant_msg = {
            "role": "assistant",
            "content": assistant_content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"token_count": token_count},
        }

        # Append messages
        messages = session.messages or []
        messages.append(user_msg)
        messages.append(assistant_msg)
        session.messages = messages
        session.message_count = len(messages)
        session.token_count = (session.token_count or 0) + token_count
        session.save()

        # Create trace
        trace = Trace.objects.create(
            owner=session.owner,
            title=f"Session: {session.name}",
            trace_kind="session",
            status="completed",
            summary=assistant_content[:200],
            token_count=token_count,
        )
        TraceEvent.objects.create(
            trace=trace,
            sequence=1,
            event_type="run_completed",
            message=assistant_content[:255],
            payload={"prompt": prompt},
        )

        return Response({
            "message": assistant_content,
            "trace_id": trace.id,
            "token_count": token_count,
            "message_count": session.message_count,
        })
```

- [ ] **Step 8: Create views — stream.py**

Create `backend/apps/sessions/views/stream.py`:

```python
import json
import time

from django.http import StreamingHttpResponse
from drf_yasg.utils import swagger_auto_schema
from rest_framework.views import APIView

from .shared import get_session_for_request


class SessionStreamView(APIView):
    """SSE streaming response for a session message."""

    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Stream session response (SSE)")
    def get(self, request, pk: int):
        session = get_session_for_request(request, pk)
        prompt = request.query_params.get("prompt", "")

        def event_stream():
            # Emit start event
            yield f"data: {json.dumps({'type': 'run_started', 'message': 'Session run started'})}\n\n"

            # Simulate streaming response — to be replaced with real agent streaming
            response_text = f"[Streaming session response to: {prompt}]"
            for i, char in enumerate(response_text):
                yield f"data: {json.dumps({'type': 'token', 'message': char})}\n\n"

            # Emit completion
            yield f"data: {json.dumps({'type': 'run_completed', 'message': response_text})}\n\n"

        return StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
```

- [ ] **Step 9: Create views — fork.py**

Create `backend/apps/sessions/views/fork.py`:

```python
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import AgentSessionSerializer
from .shared import get_session_for_request


class SessionForkView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Fork session from a message index",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "from_message": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="Message index to fork from",
                ),
            },
        ),
        responses={201: AgentSessionSerializer},
    )
    def post(self, request, pk: int):
        session = get_session_for_request(request, pk)
        from_message = request.data.get("from_message", len(session.messages))

        from ..models import AgentSession

        forked = AgentSession.objects.create(
            owner=session.owner,
            name=f"Fork of {session.name}",
            agent=session.agent,
            deep_agent=session.deep_agent,
            messages=session.messages[:from_message],
            message_count=from_message,
            forked_from=session,
            forked_at_message=from_message,
        )
        return Response(AgentSessionSerializer(forked).data, status=status.HTTP_201_CREATED)


class SessionArchiveView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Archive session")
    def post(self, request, pk: int):
        session = get_session_for_request(request, pk)
        session.is_archived = True
        session.is_active = False
        session.save(update_fields=["is_archived", "is_active"])
        return Response({"status": "archived"})
```

- [ ] **Step 10: Create urls.py**

Create `backend/apps/sessions/urls.py`:

```python
from django.urls import path

from .views import (
    SessionArchiveView,
    SessionDetailView,
    SessionForkView,
    SessionListCreateView,
    SessionSendView,
    SessionStreamView,
)

urlpatterns = [
    path("", SessionListCreateView.as_view(), name="session-list-create"),
    path("<int:pk>/", SessionDetailView.as_view(), name="session-detail"),
    path("<int:pk>/send/", SessionSendView.as_view(), name="session-send"),
    path("<int:pk>/stream/", SessionStreamView.as_view(), name="session-stream"),
    path("<int:pk>/fork/", SessionForkView.as_view(), name="session-fork"),
    path("<int:pk>/archive/", SessionArchiveView.as_view(), name="session-archive"),
]
```

- [ ] **Step 11: Add URL pattern to main urls.py**

In `backend/shipit_cloud/urls.py`, add:

```python
path("api/sessions/", include("apps.sessions.urls")),
```

- [ ] **Step 12: Run migrations and verify**

Run:
```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/backend
python manage.py makemigrations sessions
python manage.py migrate
python manage.py runserver 0.0.0.0:8000 &
curl -s http://127.0.0.1:8000/api/sessions/ | python -m json.tool
```
Expected: Empty list `[]`

---

## Task 9: Backend — Schedules App

**Files:**
- Create: `backend/apps/schedules/__init__.py`
- Create: `backend/apps/schedules/apps.py`
- Create: `backend/apps/schedules/models.py`
- Create: `backend/apps/schedules/serializers.py`
- Create: `backend/apps/schedules/tasks.py`
- Create: `backend/apps/schedules/urls.py`
- Create: `backend/apps/schedules/views/__init__.py`
- Create: `backend/apps/schedules/views/shared.py`
- Create: `backend/apps/schedules/views/list_create.py`
- Create: `backend/apps/schedules/views/detail.py`
- Create: `backend/apps/schedules/views/actions.py`
- Create: `backend/apps/schedules/views/runs.py`
- Modify: `backend/shipit_cloud/urls.py`

- [ ] **Step 1: Create app boilerplate**

Create `backend/apps/schedules/__init__.py` (empty).

Create `backend/apps/schedules/apps.py`:

```python
from django.apps import AppConfig


class SchedulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.schedules"
```

- [ ] **Step 2: Create models**

Create `backend/apps/schedules/models.py`:

```python
from django.conf import settings
from django.db import models

from apps.agents.models import AgentConfig
from apps.deep_agents.models import DeepAgent
from apps.sessions.models import AgentSession
from apps.traces.models import Trace


class AgentSchedule(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="schedules",
    )
    deep_agent = models.ForeignKey(
        DeepAgent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="schedules",
    )
    session = models.ForeignKey(
        AgentSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedules",
    )

    prompt = models.TextField()
    cron_expression = models.CharField(max_length=100)
    timezone = models.CharField(max_length=50, default="UTC")
    is_enabled = models.BooleanField(default=True)

    notify_channels = models.JSONField(default=list, blank=True)
    notify_on_failure = models.BooleanField(default=True)
    notify_on_success = models.BooleanField(default=False)

    run_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=24, blank=True)

    celery_task_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ScheduleRun(models.Model):
    schedule = models.ForeignKey(
        AgentSchedule,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    trace = models.ForeignKey(
        Trace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_runs",
    )
    status = models.CharField(max_length=24, default="running")
    output = models.TextField(blank=True)
    error = models.TextField(blank=True)
    token_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    triggered_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
```

- [ ] **Step 3: Create serializers**

Create `backend/apps/schedules/serializers.py`:

```python
from rest_framework import serializers

from .models import AgentSchedule, ScheduleRun


class ScheduleRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleRun
        fields = [
            "id", "schedule", "trace", "status", "output", "error",
            "token_count", "duration_ms", "triggered_at", "completed_at",
        ]


class AgentScheduleSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()
    deep_agent_name = serializers.SerializerMethodField()
    cron_human = serializers.SerializerMethodField()
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = AgentSchedule
        fields = [
            "id", "name", "description", "agent", "deep_agent", "session",
            "agent_name", "deep_agent_name", "prompt", "cron_expression",
            "cron_human", "timezone", "is_enabled", "notify_channels",
            "notify_on_failure", "notify_on_success", "run_count",
            "last_run_at", "next_run_at", "last_status", "latest_run",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "run_count", "last_run_at", "next_run_at",
            "last_status", "celery_task_id", "created_at", "updated_at",
        ]

    def get_agent_name(self, obj):
        return obj.agent.name if obj.agent else None

    def get_deep_agent_name(self, obj):
        return obj.deep_agent.name if obj.deep_agent else None

    def get_cron_human(self, obj):
        """Convert cron expression to human-readable string."""
        presets = {
            "* * * * *": "Every minute",
            "0 * * * *": "Every hour",
            "0 */6 * * *": "Every 6 hours",
            "0 0 * * *": "Daily at midnight",
            "0 9 * * *": "Daily at 9:00 AM",
            "0 9 * * 1": "Every Monday at 9:00 AM",
            "0 0 1 * *": "First of every month",
        }
        return presets.get(obj.cron_expression, obj.cron_expression)

    def get_latest_run(self, obj):
        run = obj.runs.first()
        if run:
            return ScheduleRunSerializer(run).data
        return None
```

- [ ] **Step 4: Create Celery task**

Create `backend/apps/schedules/tasks.py`:

```python
import logging
import time

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def run_scheduled_agent(self, schedule_id: int):
    """Execute a scheduled agent run."""
    from apps.traces.models import Trace, TraceEvent

    from .models import AgentSchedule, ScheduleRun

    try:
        schedule = AgentSchedule.objects.get(pk=schedule_id)
    except AgentSchedule.DoesNotExist:
        logger.error("Schedule %s not found", schedule_id)
        return

    run = ScheduleRun.objects.create(schedule=schedule, status="running")
    start = time.monotonic()

    try:
        # Simulate agent execution — to be replaced with real shipit_agent integration
        output = f"[Scheduled run for: {schedule.prompt}]"
        token_count = max(1, len(schedule.prompt) // 4)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        trace = Trace.objects.create(
            owner=schedule.owner,
            title=f"Schedule: {schedule.name}",
            trace_kind="schedule",
            status="completed",
            summary=output[:200],
            token_count=token_count,
            duration_ms=elapsed_ms,
        )
        TraceEvent.objects.create(
            trace=trace, sequence=1, event_type="run_completed",
            message=output[:255], payload={"schedule_id": schedule.id},
        )

        run.status = "success"
        run.output = output
        run.trace = trace
        run.token_count = token_count
        run.duration_ms = elapsed_ms
        run.completed_at = timezone.now()
        run.save()

        schedule.last_status = "success"

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        run.status = "failed"
        run.error = str(exc)
        run.duration_ms = elapsed_ms
        run.completed_at = timezone.now()
        run.save()

        schedule.last_status = "failed"
        logger.exception("Schedule %s failed", schedule_id)

    finally:
        schedule.run_count = (schedule.run_count or 0) + 1
        schedule.last_run_at = timezone.now()
        schedule.save(update_fields=["run_count", "last_run_at", "last_status"])
```

- [ ] **Step 5: Create views — shared.py, __init__.py**

Create `backend/apps/schedules/views/__init__.py`:

```python
from .list_create import ScheduleListCreateView
from .detail import ScheduleDetailView
from .actions import ScheduleToggleView, ScheduleRunNowView
from .runs import ScheduleRunListView
```

Create `backend/apps/schedules/views/shared.py`:

```python
from apps.common.auth import resolve_request_user

from ..models import AgentSchedule


def get_schedule_for_request(request, pk: int) -> AgentSchedule:
    user = resolve_request_user(request)
    return AgentSchedule.objects.get(owner=user, pk=pk)
```

- [ ] **Step 6: Create views — list_create.py**

Create `backend/apps/schedules/views/list_create.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.auth import resolve_request_user

from ..models import AgentSchedule
from ..serializers import AgentScheduleSerializer


class ScheduleListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="List schedules",
        responses={200: AgentScheduleSerializer(many=True)},
    )
    def get(self, request):
        user = resolve_request_user(request)
        qs = AgentSchedule.objects.filter(owner=user)
        return Response(AgentScheduleSerializer(qs, many=True).data)

    @swagger_auto_schema(
        operation_summary="Create schedule",
        request_body=AgentScheduleSerializer,
        responses={201: AgentScheduleSerializer},
    )
    def post(self, request):
        user = resolve_request_user(request)
        serializer = AgentScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 7: Create views — detail.py**

Create `backend/apps/schedules/views/detail.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import AgentScheduleSerializer
from .shared import get_schedule_for_request


class ScheduleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Get schedule",
        responses={200: AgentScheduleSerializer},
    )
    def get(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        return Response(AgentScheduleSerializer(schedule).data)

    @swagger_auto_schema(
        operation_summary="Update schedule",
        request_body=AgentScheduleSerializer,
        responses={200: AgentScheduleSerializer},
    )
    def put(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        serializer = AgentScheduleSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @swagger_auto_schema(operation_summary="Delete schedule")
    def delete(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        schedule.delete()
        return Response(status=204)
```

- [ ] **Step 8: Create views — actions.py**

Create `backend/apps/schedules/views/actions.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import AgentScheduleSerializer
from ..tasks import run_scheduled_agent
from .shared import get_schedule_for_request


class ScheduleToggleView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Toggle schedule enabled/disabled")
    def post(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        schedule.is_enabled = not schedule.is_enabled
        schedule.save(update_fields=["is_enabled"])
        return Response(AgentScheduleSerializer(schedule).data)


class ScheduleRunNowView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Trigger immediate execution")
    def post(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        run_scheduled_agent.delay(schedule.id)
        return Response({"status": "triggered", "schedule_id": schedule.id})
```

- [ ] **Step 9: Create views — runs.py**

Create `backend/apps/schedules/views/runs.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import ScheduleRunSerializer
from .shared import get_schedule_for_request


class ScheduleRunListView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="List schedule run history",
        responses={200: ScheduleRunSerializer(many=True)},
    )
    def get(self, request, pk: int):
        schedule = get_schedule_for_request(request, pk)
        runs = schedule.runs.all()[:50]
        return Response(ScheduleRunSerializer(runs, many=True).data)
```

- [ ] **Step 10: Create urls.py and wire up**

Create `backend/apps/schedules/urls.py`:

```python
from django.urls import path

from .views import (
    ScheduleDetailView,
    ScheduleListCreateView,
    ScheduleRunListView,
    ScheduleRunNowView,
    ScheduleToggleView,
)

urlpatterns = [
    path("", ScheduleListCreateView.as_view(), name="schedule-list-create"),
    path("<int:pk>/", ScheduleDetailView.as_view(), name="schedule-detail"),
    path("<int:pk>/toggle/", ScheduleToggleView.as_view(), name="schedule-toggle"),
    path("<int:pk>/run-now/", ScheduleRunNowView.as_view(), name="schedule-run-now"),
    path("<int:pk>/runs/", ScheduleRunListView.as_view(), name="schedule-runs"),
]
```

Add to `backend/shipit_cloud/urls.py`:

```python
path("api/schedules/", include("apps.schedules.urls")),
```

- [ ] **Step 11: Run migrations and verify**

Run:
```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/backend
python manage.py makemigrations schedules
python manage.py migrate
curl -s http://127.0.0.1:8000/api/schedules/ | python -m json.tool
```
Expected: Empty list `[]`

---

## Task 10: Backend — Webhooks App

**Files:**
- Create: `backend/apps/webhooks/__init__.py`
- Create: `backend/apps/webhooks/apps.py`
- Create: `backend/apps/webhooks/models.py`
- Create: `backend/apps/webhooks/serializers.py`
- Create: `backend/apps/webhooks/tasks.py`
- Create: `backend/apps/webhooks/urls.py`
- Create: `backend/apps/webhooks/views/__init__.py`
- Create: `backend/apps/webhooks/views/shared.py`
- Create: `backend/apps/webhooks/views/list_create.py`
- Create: `backend/apps/webhooks/views/detail.py`
- Create: `backend/apps/webhooks/views/trigger.py`
- Create: `backend/apps/webhooks/views/actions.py`
- Create: `backend/apps/webhooks/views/deliveries.py`
- Modify: `backend/shipit_cloud/urls.py`

- [ ] **Step 1: Create app boilerplate**

Create `backend/apps/webhooks/__init__.py` (empty).

Create `backend/apps/webhooks/apps.py`:

```python
from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.webhooks"
```

- [ ] **Step 2: Create models**

Create `backend/apps/webhooks/models.py`:

```python
import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models

from apps.agents.models import AgentConfig
from apps.deep_agents.models import DeepAgent
from apps.sessions.models import AgentSession
from apps.traces.models import Trace


def generate_webhook_secret():
    return secrets.token_hex(32)


class Webhook(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhooks",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="webhooks",
    )
    deep_agent = models.ForeignKey(
        DeepAgent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="webhooks",
    )
    session = models.ForeignKey(
        AgentSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhooks",
    )

    prompt_template = models.TextField()
    secret = models.CharField(max_length=64, default=generate_webhook_secret)
    is_enabled = models.BooleanField(default=True)

    trigger_count = models.PositiveIntegerField(default=0)
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def verify_signature(self, body: bytes, signature: str) -> bool:
        expected = hmac.new(
            self.secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)


class WebhookDelivery(models.Model):
    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    trace = models.ForeignKey(
        Trace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_deliveries",
    )
    payload = models.JSONField(default=dict)
    rendered_prompt = models.TextField()
    status = models.CharField(max_length=24, default="pending")
    error = models.TextField(blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    triggered_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
```

- [ ] **Step 3: Create serializers**

Create `backend/apps/webhooks/serializers.py`:

```python
from rest_framework import serializers

from .models import Webhook, WebhookDelivery


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            "id", "webhook", "trace", "payload", "rendered_prompt", "status",
            "error", "source_ip", "token_count", "duration_ms",
            "triggered_at", "completed_at",
        ]


class WebhookSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()
    deep_agent_name = serializers.SerializerMethodField()
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = Webhook
        fields = [
            "id", "name", "description", "agent", "deep_agent", "session",
            "agent_name", "deep_agent_name", "prompt_template", "secret",
            "is_enabled", "trigger_count", "last_triggered_at",
            "webhook_url", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "secret", "trigger_count", "last_triggered_at",
            "created_at", "updated_at",
        ]

    def get_agent_name(self, obj):
        return obj.agent.name if obj.agent else None

    def get_deep_agent_name(self, obj):
        return obj.deep_agent.name if obj.deep_agent else None

    def get_webhook_url(self, obj):
        return f"/api/webhooks/{obj.id}/trigger/"
```

- [ ] **Step 4: Create Celery task**

Create `backend/apps/webhooks/tasks.py`:

```python
import logging
import time

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def run_webhook_agent(self, delivery_id: int):
    """Execute an agent run triggered by a webhook."""
    from apps.traces.models import Trace, TraceEvent

    from .models import WebhookDelivery

    try:
        delivery = WebhookDelivery.objects.select_related("webhook").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        logger.error("Delivery %s not found", delivery_id)
        return

    webhook = delivery.webhook
    delivery.status = "running"
    delivery.save(update_fields=["status"])
    start = time.monotonic()

    try:
        # Simulate agent execution — to be replaced with real shipit_agent integration
        output = f"[Webhook agent response to: {delivery.rendered_prompt}]"
        token_count = max(1, len(delivery.rendered_prompt) // 4)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        trace = Trace.objects.create(
            owner=webhook.owner,
            title=f"Webhook: {webhook.name}",
            trace_kind="webhook",
            status="completed",
            summary=output[:200],
            token_count=token_count,
            duration_ms=elapsed_ms,
        )
        TraceEvent.objects.create(
            trace=trace, sequence=1, event_type="run_completed",
            message=output[:255],
            payload={"webhook_id": webhook.id, "delivery_id": delivery.id},
        )

        delivery.status = "success"
        delivery.trace = trace
        delivery.token_count = token_count
        delivery.duration_ms = elapsed_ms
        delivery.completed_at = timezone.now()
        delivery.save()

        webhook.trigger_count = (webhook.trigger_count or 0) + 1
        webhook.last_triggered_at = timezone.now()
        webhook.save(update_fields=["trigger_count", "last_triggered_at"])

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        delivery.status = "failed"
        delivery.error = str(exc)
        delivery.duration_ms = elapsed_ms
        delivery.completed_at = timezone.now()
        delivery.save()
        logger.exception("Webhook delivery %s failed", delivery_id)
```

- [ ] **Step 5: Create views**

Create `backend/apps/webhooks/views/__init__.py`:

```python
from .list_create import WebhookListCreateView
from .detail import WebhookDetailView
from .trigger import WebhookTriggerView, WebhookTestView
from .actions import WebhookToggleView, WebhookRegenerateSecretView
from .deliveries import WebhookDeliveryListView
```

Create `backend/apps/webhooks/views/shared.py`:

```python
from apps.common.auth import resolve_request_user

from ..models import Webhook


def get_webhook_for_request(request, pk: int) -> Webhook:
    user = resolve_request_user(request)
    return Webhook.objects.get(owner=user, pk=pk)
```

Create `backend/apps/webhooks/views/list_create.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.auth import resolve_request_user

from ..models import Webhook
from ..serializers import WebhookSerializer


class WebhookListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="List webhooks",
        responses={200: WebhookSerializer(many=True)},
    )
    def get(self, request):
        user = resolve_request_user(request)
        qs = Webhook.objects.filter(owner=user)
        return Response(WebhookSerializer(qs, many=True).data)

    @swagger_auto_schema(
        operation_summary="Create webhook",
        request_body=WebhookSerializer,
        responses={201: WebhookSerializer},
    )
    def post(self, request):
        user = resolve_request_user(request)
        serializer = WebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

Create `backend/apps/webhooks/views/detail.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import WebhookSerializer
from .shared import get_webhook_for_request


class WebhookDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Get webhook",
        responses={200: WebhookSerializer},
    )
    def get(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        return Response(WebhookSerializer(webhook).data)

    @swagger_auto_schema(
        operation_summary="Update webhook",
        request_body=WebhookSerializer,
        responses={200: WebhookSerializer},
    )
    def put(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        serializer = WebhookSerializer(webhook, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @swagger_auto_schema(operation_summary="Delete webhook")
    def delete(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        webhook.delete()
        return Response(status=204)
```

Create `backend/apps/webhooks/views/trigger.py`:

```python
import json
import re

from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Webhook, WebhookDelivery
from ..tasks import run_webhook_agent


def render_template(template: str, payload: dict) -> str:
    """Render {payload.key.subkey} references in a prompt template."""

    def _replacer(match):
        path = match.group(1)
        parts = path.split(".")
        value = {"payload": payload}
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, match.group(0))
                if value is match.group(0):
                    return value
            else:
                return match.group(0)
        return str(value)

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", _replacer, template)


class WebhookTriggerView(APIView):
    """Public endpoint — uses HMAC signature instead of JWT auth."""

    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Trigger webhook (HMAC-authenticated)",
        request_body=openapi.Schema(type=openapi.TYPE_OBJECT),
    )
    def post(self, request, pk: int):
        webhook = get_object_or_404(Webhook, pk=pk)
        if not webhook.is_enabled:
            return Response({"error": "Webhook disabled"}, status=404)

        signature = request.headers.get("X-Shipit-Signature", "")
        if not webhook.verify_signature(request.body, signature):
            return Response({"error": "Invalid signature"}, status=403)

        payload = request.data if isinstance(request.data, dict) else {}
        rendered_prompt = render_template(webhook.prompt_template, payload)

        delivery = WebhookDelivery.objects.create(
            webhook=webhook,
            payload=payload,
            rendered_prompt=rendered_prompt,
            source_ip=request.META.get("REMOTE_ADDR"),
            status="pending",
        )

        run_webhook_agent.delay(delivery.id)

        return Response(
            {"delivery_id": delivery.id, "status": "accepted"},
            status=202,
        )


class WebhookTestView(APIView):
    """Test endpoint — uses JWT auth, skips HMAC validation."""

    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="Test webhook (JWT-authenticated, skips HMAC)",
        request_body=openapi.Schema(type=openapi.TYPE_OBJECT),
    )
    def post(self, request, pk: int):
        from apps.common.auth import resolve_request_user

        user = resolve_request_user(request)
        webhook = Webhook.objects.get(owner=user, pk=pk)

        payload = request.data if isinstance(request.data, dict) else {}
        rendered_prompt = render_template(webhook.prompt_template, payload)

        delivery = WebhookDelivery.objects.create(
            webhook=webhook,
            payload=payload,
            rendered_prompt=rendered_prompt,
            source_ip=request.META.get("REMOTE_ADDR"),
            status="pending",
        )

        run_webhook_agent.delay(delivery.id)

        return Response(
            {"delivery_id": delivery.id, "status": "accepted", "rendered_prompt": rendered_prompt},
            status=202,
        )
```

Create `backend/apps/webhooks/views/actions.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import generate_webhook_secret
from ..serializers import WebhookSerializer
from .shared import get_webhook_for_request


class WebhookToggleView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Toggle webhook enabled/disabled")
    def post(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        webhook.is_enabled = not webhook.is_enabled
        webhook.save(update_fields=["is_enabled"])
        return Response(WebhookSerializer(webhook).data)


class WebhookRegenerateSecretView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(operation_summary="Regenerate webhook secret")
    def post(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        webhook.secret = generate_webhook_secret()
        webhook.save(update_fields=["secret"])
        return Response(WebhookSerializer(webhook).data)
```

Create `backend/apps/webhooks/views/deliveries.py`:

```python
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import WebhookDeliverySerializer
from .shared import get_webhook_for_request


class WebhookDeliveryListView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        operation_summary="List webhook deliveries",
        responses={200: WebhookDeliverySerializer(many=True)},
    )
    def get(self, request, pk: int):
        webhook = get_webhook_for_request(request, pk)
        deliveries = webhook.deliveries.all()[:50]
        return Response(WebhookDeliverySerializer(deliveries, many=True).data)
```

- [ ] **Step 6: Create urls.py and wire up**

Create `backend/apps/webhooks/urls.py`:

```python
from django.urls import path

from .views import (
    WebhookDeliveryListView,
    WebhookDetailView,
    WebhookListCreateView,
    WebhookRegenerateSecretView,
    WebhookTestView,
    WebhookToggleView,
    WebhookTriggerView,
)

urlpatterns = [
    path("", WebhookListCreateView.as_view(), name="webhook-list-create"),
    path("<int:pk>/", WebhookDetailView.as_view(), name="webhook-detail"),
    path("<int:pk>/toggle/", WebhookToggleView.as_view(), name="webhook-toggle"),
    path("<int:pk>/trigger/", WebhookTriggerView.as_view(), name="webhook-trigger"),
    path("<int:pk>/test/", WebhookTestView.as_view(), name="webhook-test"),
    path("<int:pk>/regenerate-secret/", WebhookRegenerateSecretView.as_view(), name="webhook-regenerate"),
    path("<int:pk>/deliveries/", WebhookDeliveryListView.as_view(), name="webhook-deliveries"),
]
```

Add to `backend/shipit_cloud/urls.py`:

```python
path("api/webhooks/", include("apps.webhooks.urls")),
```

- [ ] **Step 7: Run migrations and verify**

Run:
```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/backend
python manage.py makemigrations webhooks
python manage.py migrate
curl -s http://127.0.0.1:8000/api/webhooks/ | python -m json.tool
```
Expected: Empty list `[]`

---

## Task 11: Frontend — Types + API Clients

**Files:**
- Create: `frontend/src/types/session.ts`
- Create: `frontend/src/types/schedule.ts`
- Create: `frontend/src/types/webhook.ts`
- Create: `frontend/src/types/context.ts`
- Create: `frontend/src/api/sessions.ts`
- Create: `frontend/src/api/schedules.ts`
- Create: `frontend/src/api/webhooks.ts`

- [ ] **Step 1: Create TypeScript types**

Create `frontend/src/types/session.ts`:

```typescript
export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface AgentSessionRecord {
  id: number;
  name: string;
  agent: number | null;
  deep_agent: number | null;
  agent_name: string | null;
  deep_agent_name: string | null;
  messages: SessionMessage[];
  is_active: boolean;
  is_archived: boolean;
  message_count: number;
  token_count: number;
  forked_from: number | null;
  forked_at_message: number | null;
  created_at: string;
  updated_at: string;
}

export interface SessionSendResponse {
  message: string;
  trace_id: number;
  token_count: number;
  message_count: number;
}
```

Create `frontend/src/types/schedule.ts`:

```typescript
export interface ScheduleRun {
  id: number;
  schedule: number;
  trace: number | null;
  status: string;
  output: string;
  error: string;
  token_count: number;
  duration_ms: number;
  triggered_at: string;
  completed_at: string | null;
}

export interface ScheduleRecord {
  id: number;
  name: string;
  description: string;
  agent: number | null;
  deep_agent: number | null;
  session: number | null;
  agent_name: string | null;
  deep_agent_name: string | null;
  prompt: string;
  cron_expression: string;
  cron_human: string;
  timezone: string;
  is_enabled: boolean;
  notify_channels: string[];
  notify_on_failure: boolean;
  notify_on_success: boolean;
  run_count: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string;
  latest_run: ScheduleRun | null;
  created_at: string;
  updated_at: string;
}
```

Create `frontend/src/types/webhook.ts`:

```typescript
export interface WebhookDelivery {
  id: number;
  webhook: number;
  trace: number | null;
  payload: Record<string, unknown>;
  rendered_prompt: string;
  status: string;
  error: string;
  source_ip: string | null;
  token_count: number;
  duration_ms: number;
  triggered_at: string;
  completed_at: string | null;
}

export interface WebhookRecord {
  id: number;
  name: string;
  description: string;
  agent: number | null;
  deep_agent: number | null;
  session: number | null;
  agent_name: string | null;
  deep_agent_name: string | null;
  prompt_template: string;
  secret: string;
  is_enabled: boolean;
  trigger_count: number;
  last_triggered_at: string | null;
  webhook_url: string;
  created_at: string;
  updated_at: string;
}
```

Create `frontend/src/types/context.ts`:

```typescript
export interface ContextSnapshot {
  total_tokens: number;
  max_tokens: number;
  breakdown: {
    system_prompt: number;
    conversation: number;
    tool_schemas: number;
    tool_results: number;
    memory: number;
  };
  utilization: number;
  compaction_threshold: number;
  will_compact: boolean;
}
```

- [ ] **Step 2: Create API clients**

Create `frontend/src/api/sessions.ts`:

```typescript
import { apiFetch } from "../lib/api";
import type { AgentSessionRecord, SessionSendResponse } from "../types/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";
const DEFAULT_USER = import.meta.env.VITE_SHIPIT_USER ?? "demo@shipit.local";

export function listSessions(agentId?: number) {
  const params = agentId ? `?agent_id=${agentId}` : "";
  return apiFetch<AgentSessionRecord[]>(`/sessions/${params}`);
}

export function getSession(sessionId: number) {
  return apiFetch<AgentSessionRecord>(`/sessions/${sessionId}/`);
}

export function createSession(payload: { name: string; agent?: number; deep_agent?: number }) {
  return apiFetch<AgentSessionRecord>("/sessions/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteSession(sessionId: number) {
  return apiFetch<void>(`/sessions/${sessionId}/`, { method: "DELETE" });
}

export function sendMessage(sessionId: number, prompt: string) {
  return apiFetch<SessionSendResponse>(`/sessions/${sessionId}/send/`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function buildSessionStreamUrl(sessionId: number, prompt: string) {
  const params = new URLSearchParams({ prompt, shipit_user: DEFAULT_USER });
  return `${API_BASE_URL}/sessions/${sessionId}/stream/?${params.toString()}`;
}

export function forkSession(sessionId: number, fromMessage: number) {
  return apiFetch<AgentSessionRecord>(`/sessions/${sessionId}/fork/`, {
    method: "POST",
    body: JSON.stringify({ from_message: fromMessage }),
  });
}

export function archiveSession(sessionId: number) {
  return apiFetch<{ status: string }>(`/sessions/${sessionId}/archive/`, {
    method: "POST",
  });
}
```

Create `frontend/src/api/schedules.ts`:

```typescript
import { apiFetch } from "../lib/api";
import type { ScheduleRecord, ScheduleRun } from "../types/schedule";

export function listSchedules() {
  return apiFetch<ScheduleRecord[]>("/schedules/");
}

export function getSchedule(scheduleId: number) {
  return apiFetch<ScheduleRecord>(`/schedules/${scheduleId}/`);
}

export function createSchedule(payload: Partial<ScheduleRecord>) {
  return apiFetch<ScheduleRecord>("/schedules/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSchedule(scheduleId: number, payload: Partial<ScheduleRecord>) {
  return apiFetch<ScheduleRecord>(`/schedules/${scheduleId}/`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteSchedule(scheduleId: number) {
  return apiFetch<void>(`/schedules/${scheduleId}/`, { method: "DELETE" });
}

export function toggleSchedule(scheduleId: number) {
  return apiFetch<ScheduleRecord>(`/schedules/${scheduleId}/toggle/`, { method: "POST" });
}

export function runScheduleNow(scheduleId: number) {
  return apiFetch<{ status: string }>(`/schedules/${scheduleId}/run-now/`, { method: "POST" });
}

export function listScheduleRuns(scheduleId: number) {
  return apiFetch<ScheduleRun[]>(`/schedules/${scheduleId}/runs/`);
}
```

Create `frontend/src/api/webhooks.ts`:

```typescript
import { apiFetch } from "../lib/api";
import type { WebhookRecord, WebhookDelivery } from "../types/webhook";

export function listWebhooks() {
  return apiFetch<WebhookRecord[]>("/webhooks/");
}

export function getWebhook(webhookId: number) {
  return apiFetch<WebhookRecord>(`/webhooks/${webhookId}/`);
}

export function createWebhook(payload: Partial<WebhookRecord>) {
  return apiFetch<WebhookRecord>("/webhooks/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateWebhook(webhookId: number, payload: Partial<WebhookRecord>) {
  return apiFetch<WebhookRecord>(`/webhooks/${webhookId}/`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteWebhook(webhookId: number) {
  return apiFetch<void>(`/webhooks/${webhookId}/`, { method: "DELETE" });
}

export function toggleWebhook(webhookId: number) {
  return apiFetch<WebhookRecord>(`/webhooks/${webhookId}/toggle/`, { method: "POST" });
}

export function regenerateSecret(webhookId: number) {
  return apiFetch<WebhookRecord>(`/webhooks/${webhookId}/regenerate-secret/`, { method: "POST" });
}

export function listDeliveries(webhookId: number) {
  return apiFetch<WebhookDelivery[]>(`/webhooks/${webhookId}/deliveries/`);
}

export function testWebhook(webhookId: number, payload: Record<string, unknown>) {
  return apiFetch<{ delivery_id: number; status: string; rendered_prompt: string }>(
    `/webhooks/${webhookId}/test/`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
```

---

## Task 12: Frontend — ContextWindowBar Component

**Files:**
- Create: `frontend/src/components/shared/ContextWindowBar.tsx`

- [ ] **Step 1: Create ContextWindowBar**

Create `frontend/src/components/shared/ContextWindowBar.tsx`:

```tsx
import type { ContextSnapshot } from "../../types/context";


interface ContextWindowBarProps {
  snapshot: ContextSnapshot | null;
  compact?: boolean;
}


const CATEGORY_COLORS: Record<string, string> = {
  system_prompt: "bg-blue-500",
  conversation: "bg-green-500",
  tool_schemas: "bg-amber-500",
  tool_results: "bg-orange-500",
  memory: "bg-purple-500",
};

const CATEGORY_LABELS: Record<string, string> = {
  system_prompt: "System prompt",
  conversation: "Conversation",
  tool_schemas: "Tool schemas",
  tool_results: "Tool results",
  memory: "Memory context",
};

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function statusColor(utilization: number): string {
  if (utilization >= 0.75) return "text-red-400";
  if (utilization >= 0.5) return "text-amber-400";
  return "text-green-400";
}


export function ContextWindowBar({ snapshot, compact = false }: ContextWindowBarProps) {
  if (!snapshot) return null;

  const pct = Math.round(snapshot.utilization * 100);

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted">
        <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-white/5">
          {Object.entries(snapshot.breakdown).map(([key, value]) => {
            const width = snapshot.max_tokens > 0 ? (value / snapshot.max_tokens) * 100 : 0;
            if (width < 0.5) return null;
            return (
              <div
                key={key}
                className={`${CATEGORY_COLORS[key] ?? "bg-gray-500"} transition-all`}
                style={{ width: `${width}%` }}
              />
            );
          })}
        </div>
        <span className={statusColor(snapshot.utilization)}>
          {pct}% ({formatTokens(snapshot.total_tokens)} / {formatTokens(snapshot.max_tokens)})
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between text-sm">
        <span className="font-display">Context Window</span>
        <span className={`font-mono ${statusColor(snapshot.utilization)}`}>
          {formatTokens(snapshot.total_tokens)} / {formatTokens(snapshot.max_tokens)} tokens ({pct}%)
        </span>
      </div>

      {/* Segmented bar */}
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-white/5">
        {Object.entries(snapshot.breakdown).map(([key, value]) => {
          const width = snapshot.max_tokens > 0 ? (value / snapshot.max_tokens) * 100 : 0;
          if (width < 0.3) return null;
          return (
            <div
              key={key}
              className={`${CATEGORY_COLORS[key] ?? "bg-gray-500"} transition-all`}
              style={{ width: `${width}%` }}
              title={`${CATEGORY_LABELS[key]}: ${formatTokens(value)}`}
            />
          );
        })}
      </div>

      {/* Breakdown */}
      <div className="mt-3 space-y-1">
        {Object.entries(snapshot.breakdown).map(([key, value]) => {
          if (value === 0) return null;
          const categoryPct = snapshot.total_tokens > 0 ? Math.round((value / snapshot.total_tokens) * 100) : 0;
          return (
            <div key={key} className="flex items-center gap-2 text-xs text-muted">
              <div className={`h-2 w-2 rounded-full ${CATEGORY_COLORS[key] ?? "bg-gray-500"}`} />
              <span className="w-28">{CATEGORY_LABELS[key]}</span>
              <span className="font-mono">{formatTokens(value)}</span>
              <span className="text-muted/60">({categoryPct}%)</span>
            </div>
          );
        })}
      </div>

      {/* Compaction warning */}
      {snapshot.will_compact && (
        <div className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
          Compaction imminent at {Math.round(snapshot.compaction_threshold * 100)}% ({formatTokens(Math.round(snapshot.max_tokens * snapshot.compaction_threshold))})
        </div>
      )}
    </div>
  );
}
```

---

## Task 13: Frontend — Session Pages

**Files:**
- Create: `frontend/src/features/sessions/SessionListPage.tsx`
- Create: `frontend/src/features/sessions/SessionChatPage.tsx`

- [ ] **Step 1: Create SessionListPage**

Create `frontend/src/features/sessions/SessionListPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listSessions, createSession, deleteSession, archiveSession } from "../../api/sessions";
import { listAgents } from "../../api/agents";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import { StatusBadge } from "../../components/shared/StatusBadge";
import type { AgentSessionRecord } from "../../types/session";
import type { AgentRecord } from "../../types/agent";


export function SessionListPage() {
  const [sessions, setSessions] = useState<AgentSessionRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newAgentId, setNewAgentId] = useState<number | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    listSessions().then(setSessions).catch(() => undefined);
    listAgents().then(setAgents).catch(() => undefined);
  }, []);

  const handleCreate = async () => {
    if (!newName.trim() || !newAgentId) return;
    const session = await createSession({ name: newName, agent: newAgentId });
    navigate(`/sessions/${session.id}`);
  };

  const handleDelete = async (id: number) => {
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
  };

  const handleArchive = async (id: number) => {
    await archiveSession(id);
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, is_archived: true, is_active: false } : s)));
  };

  const active = sessions.filter((s) => !s.is_archived);
  const archived = sessions.filter((s) => s.is_archived);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Sessions"
        title="Chat Sessions"
        description="Multi-turn conversations with your agents. Full history, forking, and streaming."
        action={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950"
          >
            New Session
          </button>
        }
      />

      {/* Create dialog */}
      {showCreate && (
        <Panel>
          <p className="font-display text-lg">New Session</p>
          <div className="mt-4 space-y-3">
            <input
              type="text"
              placeholder="Session name..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent"
            />
            <select
              value={newAgentId ?? ""}
              onChange={(e) => setNewAgentId(Number(e.target.value) || null)}
              className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent"
            >
              <option value="">Select an agent...</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <div className="flex gap-3">
              <button type="button" onClick={handleCreate} className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
                Create
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="rounded-2xl border border-line px-4 py-3 text-sm">
                Cancel
              </button>
            </div>
          </div>
        </Panel>
      )}

      {/* Active sessions */}
      <div className="space-y-4">
        {active.map((session) => (
          <Panel key={session.id}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-display text-xl">{session.name}</p>
                <p className="mt-1 text-xs text-muted">
                  {session.agent_name ?? session.deep_agent_name ?? "No agent"} - {session.message_count} messages - {session.token_count} tokens
                </p>
              </div>
              <StatusBadge value={session.is_active ? "active" : "archived"} />
            </div>
            <div className="mt-4 flex gap-3">
              <Link to={`/sessions/${session.id}`} className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
                Open Chat
              </Link>
              <button type="button" onClick={() => handleArchive(session.id)} className="rounded-2xl border border-line px-4 py-3 text-sm">
                Archive
              </button>
              <button type="button" onClick={() => handleDelete(session.id)} className="rounded-2xl border border-red-500/30 px-4 py-3 text-sm text-red-400">
                Delete
              </button>
            </div>
          </Panel>
        ))}
        {active.length === 0 && !showCreate && (
          <Panel>
            <p className="text-sm text-muted">No active sessions. Create one to start chatting with your agents.</p>
          </Panel>
        )}
      </div>

      {/* Archived */}
      {archived.length > 0 && (
        <>
          <h3 className="font-display text-lg text-muted">Archived</h3>
          <div className="space-y-4">
            {archived.map((session) => (
              <Panel key={session.id}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-display text-lg text-muted">{session.name}</p>
                    <p className="text-xs text-muted">{session.message_count} messages</p>
                  </div>
                  <button type="button" onClick={() => handleDelete(session.id)} className="rounded-2xl border border-red-500/30 px-3 py-2 text-xs text-red-400">
                    Delete
                  </button>
                </div>
              </Panel>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create SessionChatPage**

Create `frontend/src/features/sessions/SessionChatPage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getSession, sendMessage, forkSession } from "../../api/sessions";
import { ContextWindowBar } from "../../components/shared/ContextWindowBar";
import type { AgentSessionRecord, SessionMessage } from "../../types/session";
import type { ContextSnapshot } from "../../types/context";


export function SessionChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [session, setSession] = useState<AgentSessionRecord | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [contextSnapshot, setContextSnapshot] = useState<ContextSnapshot | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (sessionId) {
      getSession(Number(sessionId)).then(setSession).catch(() => undefined);
    }
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages, streamingText]);

  const handleSend = async () => {
    if (!input.trim() || sending || !session) return;
    const prompt = input.trim();
    setInput("");
    setSending(true);
    setStreamingText("");

    // Optimistically add user message
    const userMsg: SessionMessage = {
      role: "user",
      content: prompt,
      timestamp: new Date().toISOString(),
      metadata: {},
    };
    setSession((prev) => prev ? { ...prev, messages: [...prev.messages, userMsg] } : prev);

    try {
      const response = await sendMessage(session.id, prompt);

      // Add assistant response
      const assistantMsg: SessionMessage = {
        role: "assistant",
        content: response.message,
        timestamp: new Date().toISOString(),
        metadata: { token_count: response.token_count },
      };
      setSession((prev) =>
        prev
          ? {
              ...prev,
              messages: [...prev.messages, assistantMsg],
              message_count: response.message_count,
              token_count: prev.token_count + response.token_count,
            }
          : prev
      );
    } catch {
      // Remove optimistic user message on error
      setSession((prev) =>
        prev ? { ...prev, messages: prev.messages.slice(0, -1) } : prev
      );
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFork = async (messageIndex: number) => {
    if (!session) return;
    const forked = await forkSession(session.id, messageIndex);
    window.location.href = `/sessions/${forked.id}`;
  };

  if (!session) {
    return <div className="p-8 text-muted">Loading session...</div>;
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      {/* Header */}
      <div className="border-b border-line px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link to="/sessions" className="text-muted hover:text-foreground">
              &larr;
            </Link>
            <div>
              <h1 className="font-display text-xl">{session.name}</h1>
              <p className="text-xs text-muted">
                {session.agent_name ?? session.deep_agent_name} - {session.message_count} messages
              </p>
            </div>
          </div>
        </div>
        {/* Context bar */}
        {contextSnapshot && (
          <div className="mt-2">
            <ContextWindowBar snapshot={contextSnapshot} compact />
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto max-w-3xl space-y-4">
          {session.messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`group relative max-w-[80%] rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-accent text-slate-950"
                    : "border border-line bg-surface"
                }`}
              >
                <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
                <div className="mt-1 text-xs opacity-50">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </div>

                {/* Fork button on user messages */}
                {msg.role === "user" && (
                  <button
                    type="button"
                    onClick={() => handleFork(i)}
                    className="absolute -left-8 top-1/2 -translate-y-1/2 opacity-0 transition-opacity group-hover:opacity-100"
                    title="Fork from here"
                  >
                    <span className="text-muted hover:text-foreground">&#9582;</span>
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {sending && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-line bg-surface px-4 py-3">
                <div className="flex gap-1">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted" style={{ animationDelay: "0ms" }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted" style={{ animationDelay: "150ms" }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-line px-6 py-4">
        <div className="mx-auto flex max-w-3xl gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message... (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 resize-none rounded-2xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={sending || !input.trim()}
            className="rounded-2xl bg-accent px-6 py-3 text-sm font-semibold text-slate-950 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
```

---

## Task 14: Frontend — Schedule Pages

**Files:**
- Create: `frontend/src/features/schedules/ScheduleListPage.tsx`
- Create: `frontend/src/features/schedules/ScheduleBuilderPage.tsx`
- Create: `frontend/src/features/schedules/ScheduleDetailPage.tsx`

- [ ] **Step 1: Create ScheduleListPage**

Create `frontend/src/features/schedules/ScheduleListPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listSchedules, toggleSchedule, runScheduleNow, deleteSchedule } from "../../api/schedules";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import { StatusBadge } from "../../components/shared/StatusBadge";
import type { ScheduleRecord } from "../../types/schedule";


function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}


export function ScheduleListPage() {
  const [schedules, setSchedules] = useState<ScheduleRecord[]>([]);

  useEffect(() => {
    listSchedules().then(setSchedules).catch(() => undefined);
  }, []);

  const handleToggle = async (id: number) => {
    const updated = await toggleSchedule(id);
    setSchedules((prev) => prev.map((s) => (s.id === id ? updated : s)));
  };

  const handleRunNow = async (id: number) => {
    await runScheduleNow(id);
    // Refresh after trigger
    listSchedules().then(setSchedules).catch(() => undefined);
  };

  const handleDelete = async (id: number) => {
    await deleteSchedule(id);
    setSchedules((prev) => prev.filter((s) => s.id !== id));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Schedules"
        title="Scheduled Runs"
        description="Cron-based recurring agent execution. Agents run automatically on your schedule."
        action={
          <Link to="/schedules/new" className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
            New Schedule
          </Link>
        }
      />

      <div className="space-y-4">
        {schedules.map((schedule) => (
          <Panel key={schedule.id}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-3">
                  <p className="font-display text-xl">{schedule.name}</p>
                  <StatusBadge value={schedule.is_enabled ? (schedule.last_status || "ready") : "disabled"} />
                </div>
                <p className="mt-1 text-sm text-muted">{schedule.description}</p>
              </div>
              <button
                type="button"
                onClick={() => handleToggle(schedule.id)}
                className={`relative h-6 w-11 rounded-full transition-colors ${schedule.is_enabled ? "bg-accent" : "bg-white/10"}`}
              >
                <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${schedule.is_enabled ? "translate-x-5" : ""}`} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-3 text-xs uppercase tracking-[0.24em] text-muted">
              <span>{schedule.agent_name ?? schedule.deep_agent_name ?? "No agent"}</span>
              <span>{schedule.cron_human}</span>
              <span>{schedule.run_count} runs</span>
              <span>Last: {timeAgo(schedule.last_run_at)}</span>
            </div>
            <div className="mt-4 flex gap-3">
              <button type="button" onClick={() => handleRunNow(schedule.id)} className="rounded-2xl border border-line px-4 py-3 text-sm">
                Run Now
              </button>
              <Link to={`/schedules/${schedule.id}`} className="rounded-2xl border border-line px-4 py-3 text-sm">
                View Detail
              </Link>
              <button type="button" onClick={() => handleDelete(schedule.id)} className="rounded-2xl border border-red-500/30 px-4 py-3 text-sm text-red-400">
                Delete
              </button>
            </div>
          </Panel>
        ))}
        {schedules.length === 0 && (
          <Panel>
            <p className="text-sm text-muted">No schedules yet. Create one to run agents on a recurring basis.</p>
          </Panel>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create ScheduleBuilderPage**

Create `frontend/src/features/schedules/ScheduleBuilderPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createSchedule } from "../../api/schedules";
import { listAgents } from "../../api/agents";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import type { AgentRecord } from "../../types/agent";


const CRON_PRESETS = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every 6 hours", value: "0 */6 * * *" },
  { label: "Daily at 9 AM", value: "0 9 * * *" },
  { label: "Daily at midnight", value: "0 0 * * *" },
  { label: "Weekly Monday 9 AM", value: "0 9 * * 1" },
  { label: "Monthly 1st", value: "0 0 1 * *" },
];


export function ScheduleBuilderPage() {
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentId, setAgentId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [cronExpression, setCronExpression] = useState("0 */6 * * *");
  const [customCron, setCustomCron] = useState(false);
  const [notifyOnFailure, setNotifyOnFailure] = useState(true);
  const [notifyOnSuccess, setNotifyOnSuccess] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    listAgents().then(setAgents).catch(() => undefined);
  }, []);

  const handleSave = async () => {
    if (!name.trim() || !agentId || !prompt.trim()) return;
    const schedule = await createSchedule({
      name,
      description,
      agent: agentId,
      prompt,
      cron_expression: cronExpression,
      notify_on_failure: notifyOnFailure,
      notify_on_success: notifyOnSuccess,
    });
    navigate(`/schedules/${schedule.id}`);
  };

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Schedules" title="New Schedule" description="Set up a recurring agent run." />

      <div className="mx-auto max-w-2xl space-y-6">
        <Panel>
          <p className="font-display text-lg">Basic Info</p>
          <div className="mt-4 space-y-3">
            <input type="text" placeholder="Schedule name..." value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
            <input type="text" placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
          </div>
        </Panel>

        <Panel>
          <p className="font-display text-lg">Agent</p>
          <select value={agentId ?? ""} onChange={(e) => setAgentId(Number(e.target.value) || null)} className="mt-4 w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent">
            <option value="">Select an agent...</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Panel>

        <Panel>
          <p className="font-display text-lg">Prompt</p>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="What should the agent do each run..." rows={4} className="mt-4 w-full resize-none rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
        </Panel>

        <Panel>
          <p className="font-display text-lg">Schedule</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {CRON_PRESETS.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => { setCronExpression(preset.value); setCustomCron(false); }}
                className={`rounded-xl px-3 py-2 text-xs ${cronExpression === preset.value && !customCron ? "bg-accent text-slate-950" : "border border-line"}`}
              >
                {preset.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setCustomCron(true)}
              className={`rounded-xl px-3 py-2 text-xs ${customCron ? "bg-accent text-slate-950" : "border border-line"}`}
            >
              Custom
            </button>
          </div>
          {customCron && (
            <input type="text" placeholder="0 */6 * * * (min hour dom mon dow)" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} className="mt-3 w-full rounded-xl border border-line bg-transparent px-4 py-3 font-mono text-sm outline-none focus:border-accent" />
          )}
          <p className="mt-2 text-xs text-muted">Current: {cronExpression}</p>
        </Panel>

        <Panel>
          <p className="font-display text-lg">Notifications</p>
          <div className="mt-4 space-y-3">
            <label className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={notifyOnFailure} onChange={(e) => setNotifyOnFailure(e.target.checked)} className="rounded" />
              Notify on failure
            </label>
            <label className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={notifyOnSuccess} onChange={(e) => setNotifyOnSuccess(e.target.checked)} className="rounded" />
              Notify on success
            </label>
          </div>
        </Panel>

        <button type="button" onClick={handleSave} className="w-full rounded-2xl bg-accent py-4 text-sm font-semibold text-slate-950">
          Create Schedule
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create ScheduleDetailPage**

Create `frontend/src/features/schedules/ScheduleDetailPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";

import { getSchedule, updateSchedule, deleteSchedule, toggleSchedule, runScheduleNow, listScheduleRuns } from "../../api/schedules";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import { StatusBadge } from "../../components/shared/StatusBadge";
import type { ScheduleRecord, ScheduleRun } from "../../types/schedule";


export function ScheduleDetailPage() {
  const { scheduleId } = useParams<{ scheduleId: string }>();
  const [schedule, setSchedule] = useState<ScheduleRecord | null>(null);
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cronExpression, setCronExpression] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    if (scheduleId) {
      const id = Number(scheduleId);
      getSchedule(id).then((s) => {
        setSchedule(s);
        setName(s.name);
        setPrompt(s.prompt);
        setCronExpression(s.cron_expression);
      }).catch(() => undefined);
      listScheduleRuns(id).then(setRuns).catch(() => undefined);
    }
  }, [scheduleId]);

  const handleSave = async () => {
    if (!schedule) return;
    const updated = await updateSchedule(schedule.id, { name, prompt, cron_expression: cronExpression });
    setSchedule(updated);
    setEditing(false);
  };

  const handleDelete = async () => {
    if (!schedule) return;
    await deleteSchedule(schedule.id);
    navigate("/schedules");
  };

  const handleToggle = async () => {
    if (!schedule) return;
    const updated = await toggleSchedule(schedule.id);
    setSchedule(updated);
  };

  const handleRunNow = async () => {
    if (!schedule) return;
    await runScheduleNow(schedule.id);
    listScheduleRuns(schedule.id).then(setRuns).catch(() => undefined);
  };

  if (!schedule) return <div className="p-8 text-muted">Loading...</div>;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Schedules"
        title={schedule.name}
        description={schedule.cron_human}
        action={
          <div className="flex gap-3">
            <button type="button" onClick={handleRunNow} className="rounded-2xl border border-line px-4 py-3 text-sm">
              Run Now
            </button>
            <button type="button" onClick={handleToggle} className={`rounded-2xl px-4 py-3 text-sm ${schedule.is_enabled ? "border border-line" : "bg-accent text-slate-950"}`}>
              {schedule.is_enabled ? "Disable" : "Enable"}
            </button>
          </div>
        }
      />

      <Panel>
        <div className="flex items-center justify-between">
          <p className="font-display text-lg">Configuration</p>
          <button type="button" onClick={() => setEditing(!editing)} className="text-xs text-accent">
            {editing ? "Cancel" : "Edit"}
          </button>
        </div>
        <div className="mt-4 space-y-3">
          <div>
            <label className="text-xs text-muted">Name</label>
            {editing ? (
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
            ) : (
              <p className="text-sm">{schedule.name}</p>
            )}
          </div>
          <div>
            <label className="text-xs text-muted">Agent</label>
            <p className="text-sm">{schedule.agent_name ?? schedule.deep_agent_name ?? "None"}</p>
          </div>
          <div>
            <label className="text-xs text-muted">Prompt</label>
            {editing ? (
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} className="w-full resize-none rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
            ) : (
              <p className="text-sm">{schedule.prompt}</p>
            )}
          </div>
          <div>
            <label className="text-xs text-muted">Cron Expression</label>
            {editing ? (
              <input type="text" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 font-mono text-sm outline-none focus:border-accent" />
            ) : (
              <p className="font-mono text-sm">{schedule.cron_expression} ({schedule.cron_human})</p>
            )}
          </div>
          {editing && (
            <button type="button" onClick={handleSave} className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
              Save Changes
            </button>
          )}
        </div>
      </Panel>

      {/* Run History */}
      <Panel>
        <p className="font-display text-lg">Run History ({runs.length})</p>
        <div className="mt-4 space-y-3">
          {runs.map((run) => (
            <div key={run.id} className="flex items-center justify-between rounded-xl border border-line px-4 py-3">
              <div className="flex items-center gap-3">
                <StatusBadge value={run.status} />
                <span className="text-xs text-muted">{new Date(run.triggered_at).toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted">
                <span>{run.token_count} tokens</span>
                <span>{run.duration_ms}ms</span>
                {run.trace && <a href={`/traces/${run.trace}`} className="text-accent">Trace</a>}
              </div>
            </div>
          ))}
          {runs.length === 0 && <p className="text-xs text-muted">No runs yet.</p>}
        </div>
      </Panel>

      <button type="button" onClick={handleDelete} className="w-full rounded-2xl border border-red-500/30 py-3 text-sm text-red-400">
        Delete Schedule
      </button>
    </div>
  );
}
```

---

## Task 15: Frontend — Webhook Pages

**Files:**
- Create: `frontend/src/features/webhooks/WebhookListPage.tsx`
- Create: `frontend/src/features/webhooks/WebhookBuilderPage.tsx`
- Create: `frontend/src/features/webhooks/WebhookDetailPage.tsx`

- [ ] **Step 1: Create WebhookListPage**

Create `frontend/src/features/webhooks/WebhookListPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listWebhooks, toggleWebhook, deleteWebhook } from "../../api/webhooks";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import { StatusBadge } from "../../components/shared/StatusBadge";
import type { WebhookRecord } from "../../types/webhook";


export function WebhookListPage() {
  const [webhooks, setWebhooks] = useState<WebhookRecord[]>([]);

  useEffect(() => {
    listWebhooks().then(setWebhooks).catch(() => undefined);
  }, []);

  const handleToggle = async (id: number) => {
    const updated = await toggleWebhook(id);
    setWebhooks((prev) => prev.map((w) => (w.id === id ? updated : w)));
  };

  const handleDelete = async (id: number) => {
    await deleteWebhook(id);
    setWebhooks((prev) => prev.filter((w) => w.id !== id));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Webhooks"
        title="Webhook Triggers"
        description="External services trigger agent runs via HMAC-authenticated HTTP webhooks."
        action={
          <Link to="/webhooks/new" className="rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
            New Webhook
          </Link>
        }
      />

      <div className="space-y-4">
        {webhooks.map((webhook) => (
          <Panel key={webhook.id}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-3">
                  <p className="font-display text-xl">{webhook.name}</p>
                  <StatusBadge value={webhook.is_enabled ? "active" : "disabled"} />
                </div>
                <p className="mt-1 text-sm text-muted">{webhook.description}</p>
              </div>
              <button
                type="button"
                onClick={() => handleToggle(webhook.id)}
                className={`relative h-6 w-11 rounded-full transition-colors ${webhook.is_enabled ? "bg-accent" : "bg-white/10"}`}
              >
                <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${webhook.is_enabled ? "translate-x-5" : ""}`} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-3 text-xs uppercase tracking-[0.24em] text-muted">
              <span>{webhook.agent_name ?? webhook.deep_agent_name ?? "No agent"}</span>
              <span>{webhook.trigger_count} triggers</span>
            </div>
            <div className="mt-4 flex gap-3">
              <Link to={`/webhooks/${webhook.id}`} className="rounded-2xl border border-line px-4 py-3 text-sm">
                View Detail
              </Link>
              <button type="button" onClick={() => handleDelete(webhook.id)} className="rounded-2xl border border-red-500/30 px-4 py-3 text-sm text-red-400">
                Delete
              </button>
            </div>
          </Panel>
        ))}
        {webhooks.length === 0 && (
          <Panel>
            <p className="text-sm text-muted">No webhooks yet. Create one to trigger agents from external services.</p>
          </Panel>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create WebhookBuilderPage**

Create `frontend/src/features/webhooks/WebhookBuilderPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createWebhook } from "../../api/webhooks";
import { listAgents } from "../../api/agents";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import type { AgentRecord } from "../../types/agent";


export function WebhookBuilderPage() {
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentId, setAgentId] = useState<number | null>(null);
  const [promptTemplate, setPromptTemplate] = useState("");
  const [samplePayload, setSamplePayload] = useState('{"event": "push", "repo": {"name": "shipit"}}');
  const navigate = useNavigate();

  useEffect(() => {
    listAgents().then(setAgents).catch(() => undefined);
  }, []);

  const renderPreview = (): string => {
    try {
      const payload = JSON.parse(samplePayload);
      return promptTemplate.replace(/\{payload\.([a-zA-Z0-9_.]+)\}/g, (_match, path: string) => {
        let val: unknown = payload;
        for (const key of path.split(".")) {
          if (val && typeof val === "object" && key in (val as Record<string, unknown>)) {
            val = (val as Record<string, unknown>)[key];
          } else {
            return `{payload.${path}}`;
          }
        }
        return String(val);
      });
    } catch {
      return promptTemplate;
    }
  };

  const handleSave = async () => {
    if (!name.trim() || !agentId || !promptTemplate.trim()) return;
    const webhook = await createWebhook({
      name,
      description,
      agent: agentId,
      prompt_template: promptTemplate,
    });
    navigate(`/webhooks/${webhook.id}`);
  };

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Webhooks" title="New Webhook" description="Create an HMAC-authenticated webhook trigger." />

      <div className="mx-auto max-w-2xl space-y-6">
        <Panel>
          <p className="font-display text-lg">Basic Info</p>
          <div className="mt-4 space-y-3">
            <input type="text" placeholder="Webhook name..." value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
            <input type="text" placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent" />
          </div>
        </Panel>

        <Panel>
          <p className="font-display text-lg">Agent</p>
          <select value={agentId ?? ""} onChange={(e) => setAgentId(Number(e.target.value) || null)} className="mt-4 w-full rounded-xl border border-line bg-transparent px-4 py-3 text-sm outline-none focus:border-accent">
            <option value="">Select an agent...</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Panel>

        <Panel>
          <p className="font-display text-lg">Prompt Template</p>
          <p className="mt-1 text-xs text-muted">Use {"{payload.key}"} to reference webhook payload values.</p>
          <textarea
            value={promptTemplate}
            onChange={(e) => setPromptTemplate(e.target.value)}
            placeholder={'Review this PR: {payload.pull_request.html_url}'}
            rows={4}
            className="mt-4 w-full resize-none rounded-xl border border-line bg-transparent px-4 py-3 font-mono text-sm outline-none focus:border-accent"
          />
        </Panel>

        <Panel>
          <p className="font-display text-lg">Preview</p>
          <p className="mt-1 text-xs text-muted">Sample payload for preview:</p>
          <textarea
            value={samplePayload}
            onChange={(e) => setSamplePayload(e.target.value)}
            rows={3}
            className="mt-2 w-full resize-none rounded-xl border border-line bg-transparent px-4 py-3 font-mono text-xs outline-none focus:border-accent"
          />
          <div className="mt-3 rounded-xl bg-white/5 px-4 py-3">
            <p className="text-xs text-muted">Rendered prompt:</p>
            <p className="mt-1 text-sm">{renderPreview() || "Enter a prompt template above..."}</p>
          </div>
        </Panel>

        <button type="button" onClick={handleSave} className="w-full rounded-2xl bg-accent py-4 text-sm font-semibold text-slate-950">
          Create Webhook
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create WebhookDetailPage**

Create `frontend/src/features/webhooks/WebhookDetailPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";

import { getWebhook, updateWebhook, deleteWebhook, regenerateSecret, listDeliveries, testWebhook } from "../../api/webhooks";
import { PageHeader } from "../../components/shared/PageHeader";
import { Panel } from "../../components/shared/Panel";
import { StatusBadge } from "../../components/shared/StatusBadge";
import type { WebhookRecord, WebhookDelivery } from "../../types/webhook";


export function WebhookDetailPage() {
  const { webhookId } = useParams<{ webhookId: string }>();
  const [webhook, setWebhook] = useState<WebhookRecord | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);
  const [showSecret, setShowSecret] = useState(false);
  const [testPayload, setTestPayload] = useState('{"event": "test"}');
  const [testResult, setTestResult] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (webhookId) {
      const id = Number(webhookId);
      getWebhook(id).then(setWebhook).catch(() => undefined);
      listDeliveries(id).then(setDeliveries).catch(() => undefined);
    }
  }, [webhookId]);

  const handleRegenerate = async () => {
    if (!webhook) return;
    const updated = await regenerateSecret(webhook.id);
    setWebhook(updated);
    setShowSecret(true);
  };

  const handleTest = async () => {
    if (!webhook) return;
    try {
      const payload = JSON.parse(testPayload);
      const result = await testWebhook(webhook.id, payload);
      setTestResult(`Delivery #${result.delivery_id} — ${result.rendered_prompt}`);
      listDeliveries(webhook.id).then(setDeliveries).catch(() => undefined);
    } catch {
      setTestResult("Invalid JSON payload");
    }
  };

  const handleDelete = async () => {
    if (!webhook) return;
    await deleteWebhook(webhook.id);
    navigate("/webhooks");
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => undefined);
  };

  if (!webhook) return <div className="p-8 text-muted">Loading...</div>;

  const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";
  const webhookUrl = `${apiBase}/webhooks/${webhook.id}/trigger/`;
  const curlExample = `curl -X POST ${webhookUrl} \\
  -H "X-Shipit-Signature: sha256=$(echo -n '${testPayload}' | openssl dgst -sha256 -hmac '${webhook.secret}' | cut -d' ' -f2)" \\
  -H "Content-Type: application/json" \\
  -d '${testPayload}'`;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Webhooks" title={webhook.name} description={webhook.agent_name ?? webhook.deep_agent_name ?? "No agent"} />

      {/* Webhook URL + Secret */}
      <Panel>
        <p className="font-display text-lg">Endpoint</p>
        <div className="mt-4 space-y-3">
          <div>
            <label className="text-xs text-muted">Webhook URL</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-xl bg-white/5 px-4 py-3 font-mono text-xs">{webhookUrl}</code>
              <button type="button" onClick={() => copyToClipboard(webhookUrl)} className="rounded-xl border border-line px-3 py-3 text-xs">Copy</button>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted">Secret</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-xl bg-white/5 px-4 py-3 font-mono text-xs">
                {showSecret ? webhook.secret : "••••••••••••••••••••••••••••••••"}
              </code>
              <button type="button" onClick={() => setShowSecret(!showSecret)} className="rounded-xl border border-line px-3 py-3 text-xs">
                {showSecret ? "Hide" : "Show"}
              </button>
              <button type="button" onClick={() => copyToClipboard(webhook.secret)} className="rounded-xl border border-line px-3 py-3 text-xs">Copy</button>
              <button type="button" onClick={handleRegenerate} className="rounded-xl border border-amber-500/30 px-3 py-3 text-xs text-amber-400">Regenerate</button>
            </div>
          </div>
        </div>
      </Panel>

      {/* cURL Example */}
      <Panel>
        <p className="font-display text-lg">cURL Example</p>
        <div className="relative mt-4">
          <pre className="overflow-x-auto rounded-xl bg-white/5 p-4 font-mono text-xs">{curlExample}</pre>
          <button type="button" onClick={() => copyToClipboard(curlExample)} className="absolute right-2 top-2 rounded-lg border border-line px-2 py-1 text-xs">Copy</button>
        </div>
      </Panel>

      {/* Test */}
      <Panel>
        <p className="font-display text-lg">Send Test</p>
        <textarea value={testPayload} onChange={(e) => setTestPayload(e.target.value)} rows={3} className="mt-4 w-full resize-none rounded-xl border border-line bg-transparent px-4 py-3 font-mono text-xs outline-none focus:border-accent" />
        <button type="button" onClick={handleTest} className="mt-3 rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-slate-950">
          Send Test
        </button>
        {testResult && <p className="mt-3 text-xs text-muted">{testResult}</p>}
      </Panel>

      {/* Delivery History */}
      <Panel>
        <p className="font-display text-lg">Deliveries ({deliveries.length})</p>
        <div className="mt-4 space-y-3">
          {deliveries.map((d) => (
            <div key={d.id} className="rounded-xl border border-line px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <StatusBadge value={d.status} />
                  <span className="text-xs text-muted">{new Date(d.triggered_at).toLocaleString()}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted">
                  <span>{d.token_count} tokens</span>
                  <span>{d.duration_ms}ms</span>
                  {d.trace && <a href={`/traces/${d.trace}`} className="text-accent">Trace</a>}
                </div>
              </div>
              <p className="mt-2 text-xs text-muted">{d.rendered_prompt.slice(0, 200)}</p>
            </div>
          ))}
          {deliveries.length === 0 && <p className="text-xs text-muted">No deliveries yet.</p>}
        </div>
      </Panel>

      <button type="button" onClick={handleDelete} className="w-full rounded-2xl border border-red-500/30 py-3 text-sm text-red-400">
        Delete Webhook
      </button>
    </div>
  );
}
```

---

## Task 16: Frontend — Router + Sidebar Updates

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/components/layout/AppShell.tsx`

- [ ] **Step 1: Update router.tsx**

Add new imports and routes to `frontend/src/router.tsx`:

New imports:
```typescript
import { SessionListPage } from "./features/sessions/SessionListPage";
import { SessionChatPage } from "./features/sessions/SessionChatPage";
import { ScheduleListPage } from "./features/schedules/ScheduleListPage";
import { ScheduleBuilderPage } from "./features/schedules/ScheduleBuilderPage";
import { ScheduleDetailPage } from "./features/schedules/ScheduleDetailPage";
import { WebhookListPage } from "./features/webhooks/WebhookListPage";
import { WebhookBuilderPage } from "./features/webhooks/WebhookBuilderPage";
import { WebhookDetailPage } from "./features/webhooks/WebhookDetailPage";
```

New routes (add inside the children array, after the Traces section):
```typescript
// Sessions
{ path: "sessions", element: <SessionListPage /> },
{ path: "sessions/:sessionId", element: <SessionChatPage /> },

// Schedules
{ path: "schedules", element: <ScheduleListPage /> },
{ path: "schedules/new", element: <ScheduleBuilderPage /> },
{ path: "schedules/:scheduleId", element: <ScheduleDetailPage /> },

// Webhooks
{ path: "webhooks", element: <WebhookListPage /> },
{ path: "webhooks/new", element: <WebhookBuilderPage /> },
{ path: "webhooks/:webhookId", element: <WebhookDetailPage /> },
```

- [ ] **Step 2: Update AppShell.tsx sidebar**

In `frontend/src/components/layout/AppShell.tsx`, add a new "Automate" section to the `sections` array after the "Connect" section:

```typescript
{
  title: "Automate",
  items: [
    { label: "Sessions", to: "/sessions", icon: "💬" },
    { label: "Schedules", to: "/schedules", icon: "⏰" },
    { label: "Webhooks", to: "/webhooks", icon: "⚡" },
  ],
},
```

- [ ] **Step 3: Verify frontend compiles**

Run:
```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/frontend
npx tsc --noEmit
```
Expected: No errors

---

## Task 17: Backend — Migrations + End-to-End Verification

- [ ] **Step 1: Run all migrations**

```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/backend
python manage.py makemigrations sessions schedules webhooks
python manage.py migrate
```

- [ ] **Step 2: Verify all API endpoints**

```bash
# Sessions
curl -s http://127.0.0.1:8000/api/sessions/ | python -m json.tool

# Schedules
curl -s http://127.0.0.1:8000/api/schedules/ | python -m json.tool

# Webhooks
curl -s http://127.0.0.1:8000/api/webhooks/ | python -m json.tool
```
Expected: Empty lists for each

- [ ] **Step 3: Test CRUD flow for sessions**

```bash
# Create session
curl -s -X POST http://127.0.0.1:8000/api/sessions/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Session", "agent": 1}' | python -m json.tool

# Send message
curl -s -X POST http://127.0.0.1:8000/api/sessions/1/send/ \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}' | python -m json.tool
```

- [ ] **Step 4: Test CRUD flow for schedules**

```bash
curl -s -X POST http://127.0.0.1:8000/api/schedules/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Health Check", "agent": 1, "prompt": "Check server health", "cron_expression": "0 */6 * * *"}' | python -m json.tool
```

- [ ] **Step 5: Test webhook creation and HMAC trigger**

```bash
# Create webhook
curl -s -X POST http://127.0.0.1:8000/api/webhooks/ \
  -H "Content-Type: application/json" \
  -d '{"name": "PR Review", "agent": 1, "prompt_template": "Review PR: {payload.pr_url}"}' | python -m json.tool

# Test trigger (via test endpoint, skips HMAC)
curl -s -X POST http://127.0.0.1:8000/api/webhooks/1/test/ \
  -H "Content-Type: application/json" \
  -d '{"pr_url": "https://github.com/org/repo/pull/42"}' | python -m json.tool
```

- [ ] **Step 6: Verify frontend loads**

```bash
cd /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/frontend
npm run dev &
# Open http://localhost:5173/sessions, /schedules, /webhooks in browser
```
