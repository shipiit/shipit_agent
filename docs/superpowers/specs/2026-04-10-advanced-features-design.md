# SHIPIT Advanced Features — Design Spec

**Date:** 2026-04-10
**Status:** Approved — Ready for Implementation
**Scope:** 4 features across shipit_agent lib + shipit_ui platform (backend + frontend)

---

## Overview

Four advanced features that make SHIPIT a production-grade agent platform:

1. **Scheduled Agent Runs** — Cron-based recurring agent execution via Celery
2. **Webhook Triggers** — External services trigger agent runs via HMAC-authenticated HTTP webhooks
3. **Session Persistence** — Multi-turn chat sessions with conversation history, forking, archiving
4. **Context Window Visualization** — Real-time token usage breakdown with compaction warnings

Each feature works independently but links together:
- Scheduled runs can optionally persist to a session
- Webhooks can optionally feed into an existing session
- Context window viz appears in session chat, agent runs, and deep agent studio
- All runs create Traces for observability

---

## Architecture Decisions

| Decision | Choice | Why |
|---|---|---|
| Scheduler backend | Celery + Redis + django-celery-beat | Production-grade, Redis already in Docker Compose |
| Webhook auth | HMAC-SHA256 signatures | Industry standard (GitHub, Stripe pattern) |
| Session UI | Full chat with streaming | User requested powerful UX |
| Feature isolation | Separate Django apps | Matches existing codebase pattern |
| Agent lib support | New modules in shipit_agent | Features work with lib standalone, not just the platform |

---

## Feature 1: Scheduled Agent Runs

### 1.1 Agent Lib — `ScheduleRunner`

New module: `shipit_agent/schedule.py`

```python
from dataclasses import dataclass, field
from typing import Any, Iterator

from .agent import Agent
from .models import AgentEvent, AgentResult


@dataclass(slots=True)
class ScheduleResult:
    """Result of a scheduled execution."""
    agent_result: AgentResult
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleRunner:
    """Executes an agent run on behalf of a scheduler.

    Works with any agent type (Agent, GoalAgent, Supervisor, etc.)
    since they all expose .run() and .stream().
    """
    agent: Any  # Agent | GoalAgent | Supervisor | etc.

    def execute(self, prompt: str, session_id: str | None = None) -> ScheduleResult:
        """Run the agent, optionally continuing an existing session."""
        if session_id and hasattr(self.agent, "chat_session"):
            chat = self.agent.chat_session(session_id)
            result = chat.send(prompt)
        else:
            result = self.agent.run(prompt)

        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "session_id": session_id,
                "token_count": sum(result.metadata.get("usage", {}).values()),
            },
        )

    def execute_stream(
        self, prompt: str, session_id: str | None = None
    ) -> Iterator[AgentEvent]:
        """Streaming execution for real-time monitoring."""
        if session_id and hasattr(self.agent, "chat_session"):
            chat = self.agent.chat_session(session_id)
            yield from chat.stream(prompt)
        else:
            yield from self.agent.stream(prompt)
```

**Public API addition in `__init__.py`:**
- `ScheduleRunner`, `ScheduleResult`

### 1.2 Backend — `schedules` Django App

**Location:** `backend/apps/schedules/`

**Models (`models.py`):**

```python
from django.conf import settings
from django.db import models

from apps.agents.models import AgentConfig
from apps.deep_agents.models import DeepAgent
from apps.sessions.models import AgentSession
from apps.traces.models import Trace


class AgentSchedule(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="schedules"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Target — exactly one must be set
    agent = models.ForeignKey(
        AgentConfig, on_delete=models.CASCADE, null=True, blank=True, related_name="schedules"
    )
    deep_agent = models.ForeignKey(
        DeepAgent, on_delete=models.CASCADE, null=True, blank=True, related_name="schedules"
    )

    # Optional session persistence
    session = models.ForeignKey(
        AgentSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules"
    )

    prompt = models.TextField()
    cron_expression = models.CharField(max_length=100)  # e.g. "0 */6 * * *"
    timezone = models.CharField(max_length=50, default="UTC")
    is_enabled = models.BooleanField(default=True)

    # Notifications
    notify_channels = models.JSONField(default=list, blank=True)  # ["email", "webhook", "slack"]
    notify_on_failure = models.BooleanField(default=True)
    notify_on_success = models.BooleanField(default=False)

    # Tracking
    run_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=24, blank=True)  # "success", "failed", "running"

    # Celery-beat link
    celery_task_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ScheduleRun(models.Model):
    """Log of each scheduled execution."""
    schedule = models.ForeignKey(
        AgentSchedule, on_delete=models.CASCADE, related_name="runs"
    )
    trace = models.ForeignKey(
        Trace, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedule_runs"
    )
    status = models.CharField(max_length=24, default="running")  # running, success, failed
    output = models.TextField(blank=True)
    error = models.TextField(blank=True)
    token_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    triggered_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
```

**Celery task (`tasks.py`):**

```python
from celery import shared_task

@shared_task(bind=True, max_retries=2)
def run_scheduled_agent(self, schedule_id: int):
    """Execute a scheduled agent run."""
    # 1. Load AgentSchedule
    # 2. Build agent from AgentConfig or DeepAgent
    # 3. Create ScheduleRun record (status=running)
    # 4. Use ScheduleRunner.execute(prompt, session_id)
    # 5. Create Trace from events
    # 6. Update ScheduleRun (status=success/failed, output, duration, tokens)
    # 7. Update AgentSchedule (last_run_at, next_run_at, run_count, last_status)
    # 8. Send notifications if configured
```

**Celery-beat sync:** On schedule create/update, sync to `django_celery_beat.PeriodicTask` with the cron expression. On delete, remove the PeriodicTask.

**API endpoints:**

```
GET    /api/schedules/                  # List user's schedules
POST   /api/schedules/                  # Create schedule (auto-syncs celery-beat)
GET    /api/schedules/{id}/             # Schedule detail
PUT    /api/schedules/{id}/             # Update schedule
DELETE /api/schedules/{id}/             # Delete schedule + celery task
POST   /api/schedules/{id}/toggle/      # Enable/disable
POST   /api/schedules/{id}/run-now/     # Trigger immediate execution
GET    /api/schedules/{id}/runs/        # Run history
GET    /api/schedules/{id}/runs/{rid}/  # Single run detail with trace link
```

**Serializer fields:**
- Read: id, name, description, agent (nested summary), deep_agent (nested summary), session (nested summary), prompt, cron_expression, cron_human (computed: "Every 6 hours"), timezone, is_enabled, notify_channels, notify_on_failure, notify_on_success, run_count, last_run_at, next_run_at, last_status, created_at
- Write: name, description, agent_id, deep_agent_id, session_id, prompt, cron_expression, timezone, is_enabled, notify_channels, notify_on_failure, notify_on_success

### 1.3 Frontend — `features/schedules/`

**API client (`api/schedules.ts`):**
- `listSchedules()`, `getSchedule(id)`, `createSchedule(payload)`, `updateSchedule(id, payload)`, `deleteSchedule(id)`, `toggleSchedule(id)`, `runScheduleNow(id)`, `listScheduleRuns(id)`

**Pages:**

**`ScheduleListPage.tsx`:**
- Table: name, target agent/deep-agent (badge), cron expression (human-readable), status indicator (green=enabled, gray=disabled, red=last-failed), next run (relative time), last run, run count
- Actions: toggle enable, run now, edit, delete
- Empty state with "Create your first schedule" CTA

**`ScheduleBuilderPage.tsx`:**
- Step 1: Name + description
- Step 2: Pick agent or deep-agent (SearchSelect from existing)
- Step 3: Prompt input (textarea with variable hints)
- Step 4: Cron expression builder — preset buttons ("Every hour", "Every 6 hours", "Daily at 9am", "Weekly Monday", "Custom") + custom cron input with real-time human-readable preview + next 5 run times preview
- Step 5: Optional session — create new or link existing
- Step 6: Notifications — checkboxes for email, webhook, slack; toggle for on-failure/on-success
- Save button

**`ScheduleDetailPage.tsx`:**
- Editable form (same as builder but pre-filled)
- Run history table below: status badge, output preview, duration, tokens, triggered time, link to trace
- "Run Now" button in header
- Delete with confirmation

**Routes:**
- `/schedules` → ScheduleListPage
- `/schedules/new` → ScheduleBuilderPage
- `/schedules/:id` → ScheduleDetailPage

---

## Feature 2: Webhook Triggers

### 2.1 Agent Lib — `WebhookPayloadTool` + `PromptTemplate`

**New module: `shipit_agent/tools/webhook_payload.py`**

```python
from dataclasses import dataclass, field
from typing import Any

from .base import Tool, ToolContext, ToolOutput


@dataclass(slots=True)
class WebhookPayloadTool:
    """Tool that gives an agent access to the webhook payload that triggered it.

    The agent can query nested paths like 'pull_request.title' or get the full payload.
    """
    name: str = "webhook_payload"
    description: str = (
        "Access the webhook payload that triggered this agent run. "
        "Pass a dot-separated path to get a nested value (e.g. 'pull_request.title'), "
        "or pass no path to get the full payload."
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
                        "description": "Dot-separated path to a nested value, e.g. 'pull_request.title'. Empty for full payload.",
                    }
                },
            },
        }

    def run(self, context: ToolContext, path: str = "") -> ToolOutput:
        if not path:
            return ToolOutput(text=json.dumps(self.payload, indent=2), metadata={})

        value = self.payload
        for key in path.split("."):
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                return ToolOutput(text=f"Path '{path}' not found in payload", metadata={})

        if isinstance(value, (dict, list)):
            return ToolOutput(text=json.dumps(value, indent=2), metadata={})
        return ToolOutput(text=str(value), metadata={})
```

**New module: `shipit_agent/templates.py`**

```python
import re
from dataclasses import dataclass


@dataclass(slots=True)
class PromptTemplate:
    """Renders prompt templates with {payload.key.subkey} variable references."""
    template: str

    def render(self, **context: object) -> str:
        def replacer(match: re.Match) -> str:
            path = match.group(1)
            parts = path.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, match.group(0))
                else:
                    return match.group(0)
            return str(value)

        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", replacer, self.template)

    def variables(self) -> list[str]:
        return re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", self.template)
```

**Public API additions:**
- `WebhookPayloadTool`, `PromptTemplate`

### 2.2 Backend — `webhooks` Django App

**Location:** `backend/apps/webhooks/`

**Models (`models.py`):**

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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webhooks"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Target — exactly one must be set
    agent = models.ForeignKey(
        AgentConfig, on_delete=models.CASCADE, null=True, blank=True, related_name="webhooks"
    )
    deep_agent = models.ForeignKey(
        DeepAgent, on_delete=models.CASCADE, null=True, blank=True, related_name="webhooks"
    )

    # Optional session persistence
    session = models.ForeignKey(
        AgentSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhooks"
    )

    prompt_template = models.TextField()  # supports {payload.key} references
    secret = models.CharField(max_length=64, default=generate_webhook_secret)
    is_enabled = models.BooleanField(default=True)

    # Tracking
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
    """Log of each webhook trigger."""
    webhook = models.ForeignKey(
        Webhook, on_delete=models.CASCADE, related_name="deliveries"
    )
    trace = models.ForeignKey(
        Trace, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhook_deliveries"
    )
    payload = models.JSONField(default=dict)
    rendered_prompt = models.TextField()
    status = models.CharField(max_length=24, default="pending")  # pending, running, success, failed
    error = models.TextField(blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    triggered_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
```

**Trigger view (public, HMAC-authed):**

```python
class WebhookTriggerView(APIView):
    """Public endpoint — no JWT auth, uses HMAC signature instead."""
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        webhook = get_object_or_404(Webhook, pk=pk)
        if not webhook.is_enabled:
            return Response({"error": "Webhook disabled"}, status=404)

        # Validate HMAC
        signature = request.headers.get("X-Shipit-Signature", "")
        if not webhook.verify_signature(request.body, signature):
            return Response({"error": "Invalid signature"}, status=403)

        # Render prompt
        payload = request.data
        template = PromptTemplate(webhook.prompt_template)
        rendered_prompt = template.render(payload=payload)

        # Create delivery record
        delivery = WebhookDelivery.objects.create(
            webhook=webhook, payload=payload, rendered_prompt=rendered_prompt,
            source_ip=request.META.get("REMOTE_ADDR"), status="pending",
        )

        # Dispatch async via Celery
        run_webhook_agent.delay(delivery.id)

        return Response({"delivery_id": delivery.id, "status": "accepted"}, status=202)
```

**API endpoints:**

```
GET    /api/webhooks/                        # List user's webhooks
POST   /api/webhooks/                        # Create webhook
GET    /api/webhooks/{id}/                   # Webhook detail
PUT    /api/webhooks/{id}/                   # Update webhook
DELETE /api/webhooks/{id}/                   # Delete webhook
POST   /api/webhooks/{id}/toggle/            # Enable/disable
POST   /api/webhooks/{id}/regenerate-secret/ # Generate new secret
GET    /api/webhooks/{id}/deliveries/        # Delivery history
POST   /api/webhooks/{id}/trigger/           # Public trigger (HMAC auth)
POST   /api/webhooks/{id}/test/              # Test trigger (JWT auth, skips HMAC)
```

### 2.3 Frontend — `features/webhooks/`

**API client (`api/webhooks.ts`):**
- `listWebhooks()`, `getWebhook(id)`, `createWebhook(payload)`, `updateWebhook(id, payload)`, `deleteWebhook(id)`, `toggleWebhook(id)`, `regenerateSecret(id)`, `listDeliveries(id)`, `testWebhook(id, payload)`

**Pages:**

**`WebhookListPage.tsx`:**
- Table: name, target agent (badge), trigger count, last triggered (relative), enabled toggle
- Actions: test, edit, delete
- Empty state

**`WebhookBuilderPage.tsx`:**
- Name + description
- Pick agent or deep-agent
- Prompt template editor with syntax highlighting for `{payload.xxx}` variables, live preview panel showing rendered output with sample payload
- Optional session link
- On save: displays webhook URL, secret, and ready-to-copy cURL example:
  ```
  curl -X POST https://your-domain/api/webhooks/42/trigger/ \
    -H "X-Shipit-Signature: sha256=$(echo -n '{"event":"push"}' | openssl dgst -sha256 -hmac 'YOUR_SECRET')" \
    -H "Content-Type: application/json" \
    -d '{"event":"push"}'
  ```

**`WebhookDetailPage.tsx`:**
- Editable form
- Secret display (masked, click to reveal, copy button, regenerate)
- Webhook URL (copy button)
- cURL example section
- "Send Test" button with JSON payload editor
- Delivery history table: status badge, payload preview (expandable), rendered prompt, duration, trace link, timestamp

**Routes:**
- `/webhooks` → WebhookListPage
- `/webhooks/new` → WebhookBuilderPage
- `/webhooks/:id` → WebhookDetailPage

---

## Feature 3: Session Persistence

### 3.1 Agent Lib — `SessionManager`

New module: `shipit_agent/session_manager.py`

```python
import uuid
from dataclasses import dataclass
from typing import Any

from .agent import Agent
from .chat_session import AgentChatSession
from .stores.session import SessionRecord, SessionStore


@dataclass(slots=True)
class SessionManager:
    """Manages multiple chat sessions with lifecycle control.

    Provides create/resume/list/archive/fork operations over a SessionStore.
    """
    session_store: SessionStore

    def create(
        self, agent: Any, name: str = "", metadata: dict[str, Any] | None = None
    ) -> AgentChatSession:
        """Create a new chat session."""
        session_id = str(uuid.uuid4())
        record = SessionRecord(
            session_id=session_id,
            messages=[],
            metadata={"name": name, **(metadata or {})},
        )
        self.session_store.save(record)
        return agent.chat_session(session_id)

    def resume(self, agent: Any, session_id: str) -> AgentChatSession:
        """Resume an existing session with full conversation history."""
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id} not found")
        return agent.chat_session(session_id)

    def list_sessions(self) -> list[SessionRecord]:
        """List all sessions in the store."""
        if hasattr(self.session_store, "list_all"):
            return self.session_store.list_all()
        return []

    def archive(self, session_id: str) -> None:
        """Mark a session as archived."""
        record = self.session_store.load(session_id)
        if record:
            record.metadata["archived"] = True
            self.session_store.save(record)

    def fork(self, agent: Any, session_id: str, from_message: int = -1) -> AgentChatSession:
        """Fork a session from a specific message index, creating a branch."""
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id} not found")

        new_id = str(uuid.uuid4())
        messages = record.messages[:from_message] if from_message > 0 else record.messages[:]
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

Also add `list_all()` method to `InMemorySessionStore` and `FileSessionStore`.

**Public API additions:**
- `SessionManager`

### 3.2 Backend — `sessions` Django App

**Location:** `backend/apps/sessions/`

**Models (`models.py`):**

```python
from django.conf import settings
from django.db import models

from apps.agents.models import AgentConfig
from apps.deep_agents.models import DeepAgent


class AgentSession(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_sessions"
    )
    name = models.CharField(max_length=200)

    # Target — exactly one must be set
    agent = models.ForeignKey(
        AgentConfig, on_delete=models.CASCADE, null=True, blank=True, related_name="sessions"
    )
    deep_agent = models.ForeignKey(
        DeepAgent, on_delete=models.CASCADE, null=True, blank=True, related_name="sessions"
    )

    messages = models.JSONField(default=list)
    # Each message: {"role": "user"|"assistant", "content": "...", "timestamp": "...", "metadata": {...}}

    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    message_count = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)

    # Fork tracking
    forked_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="forks"
    )
    forked_at_message = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
```

**API endpoints:**

```
GET    /api/sessions/                    # List user's sessions (filterable by agent_id, is_active)
POST   /api/sessions/                    # Create session
GET    /api/sessions/{id}/               # Session detail (includes messages)
PUT    /api/sessions/{id}/               # Update name/metadata
DELETE /api/sessions/{id}/               # Delete session
POST   /api/sessions/{id}/send/          # Send message, get response
GET    /api/sessions/{id}/stream/?prompt= # SSE streaming response
POST   /api/sessions/{id}/fork/          # Fork from message index
POST   /api/sessions/{id}/archive/       # Archive session
GET    /api/sessions/{id}/messages/      # Paginated message history
```

**Send view — the core interaction:**

```python
class SessionSendView(APIView):
    def post(self, request, pk: int):
        session = get_object_or_404(AgentSession, pk=pk, owner=request.user)
        prompt = request.data.get("prompt", "")

        # Build agent from session's linked agent/deep_agent
        agent = build_agent_from_config(session.agent or session.deep_agent)

        # Load conversation history into agent
        agent.history = [Message(**m) for m in session.messages]

        # Run agent
        result = agent.run(prompt)

        # Append user message + assistant response to session
        session.messages.append({
            "role": "user", "content": prompt,
            "timestamp": now().isoformat(), "metadata": {},
        })
        session.messages.append({
            "role": "assistant", "content": result.output,
            "timestamp": now().isoformat(),
            "metadata": {"token_count": sum(result.metadata.get("usage", {}).values())},
        })
        session.message_count = len(session.messages)
        session.token_count += sum(result.metadata.get("usage", {}).values())
        session.save()

        # Create trace
        trace = create_trace_from_result(session.owner, result, f"Session: {session.name}")

        return Response({
            "message": result.output,
            "events": [e.to_dict() for e in result.events],
            "trace_id": trace.id,
            "context_snapshot": result.metadata.get("context_snapshot"),
        })
```

**Stream view — SSE for real-time:**

```python
class SessionStreamView(APIView):
    def get(self, request, pk: int):
        session = get_object_or_404(AgentSession, pk=pk, owner=request.user)
        prompt = request.query_params.get("prompt", "")

        agent = build_agent_from_config(session.agent or session.deep_agent)
        agent.history = [Message(**m) for m in session.messages]

        def event_stream():
            for event in agent.stream(prompt):
                yield f"data: {json.dumps(event.to_dict())}\n\n"
            # After stream completes, append messages to session (same as send)
            ...

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")
```

### 3.3 Frontend — `features/sessions/`

**API client (`api/sessions.ts`):**
- `listSessions(agentId?)`, `getSession(id)`, `createSession(payload)`, `deleteSession(id)`, `sendMessage(id, prompt)`, `buildSessionStreamUrl(id, prompt)`, `forkSession(id, messageIndex)`, `archiveSession(id)`

**Pages:**

**`SessionListPage.tsx`:**
- Sessions grouped by agent with collapsible sections
- Each row: session name, agent badge, message count, token count, last active (relative), status (active/archived)
- Filters: by agent, active/archived
- Search by session name
- Actions: open chat, archive, delete

**`SessionChatPage.tsx` — the full chat experience:**

```
┌─────────────────────────────────────────────────────────────┐
│ ← Back   Session: "Research Q2 Metrics"    🤖 research-bot  │
│ ContextWindowBar: ████████░░░░░░░░ 34% (43,891 / 128,000)  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 👤 Find all Q2 revenue metrics from the reports     │ ⑂  │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 🤖 I'll search the knowledge base for Q2 metrics.  │    │
│  │                                                     │    │
│  │ ┌─ 🔧 Tool: knowledge_search ──────────────────┐   │    │
│  │ │ query: "Q2 revenue metrics"                   │   │    │
│  │ │ results: 4 chunks matched                     │   │    │
│  │ └──────────────────────────────────────────────┘   │    │
│  │                                                     │    │
│  │ Here are the Q2 revenue metrics I found:            │    │
│  │ - Total revenue: $4.2M (↑ 18% QoQ)                │    │
│  │ - ARR: $16.8M                                      │    │
│  │ - New customers: 47                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 👤 Now compare those with Q1                        │ ⑂  │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 🤖 ████▌ Searching Q1 data...                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ [Type your message...                              ] [Send] │
└─────────────────────────────────────────────────────────────┘
```

**UI details:**
- Message bubbles: user (right-aligned, accent color), assistant (left-aligned, subtle bg)
- Markdown rendering in assistant messages (code blocks, lists, bold, links)
- Tool call visualization: collapsible cards within assistant messages showing tool name, input, output
- Streaming: text appears character-by-character, typing indicator dots while waiting
- Fork button (⑂) on each user message — forks the conversation from that point
- Auto-scroll to bottom on new messages, scroll-up to load history
- ContextWindowBar at top (from Feature 4) — live-updates during streaming
- Keyboard: Enter to send, Shift+Enter for newline

**Routes:**
- `/sessions` → SessionListPage
- `/sessions/:id` → SessionChatPage

---

## Feature 4: Context Window Visualization

### 4.1 Agent Lib — `ContextTracker`

New module: `shipit_agent/context_tracker.py`

```python
from dataclasses import dataclass, field
from typing import Any

from .hooks import AgentHooks
from .models import AgentEvent, Message


@dataclass(slots=True)
class ContextSnapshot:
    """Point-in-time snapshot of context window utilization."""
    total_tokens: int
    max_tokens: int
    breakdown: dict[str, int]  # system_prompt, conversation, tool_schemas, tool_results, memory
    utilization: float  # 0.0-1.0
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

    Can be used standalone or plugged into AgentHooks for automatic tracking.
    Emits 'context_snapshot' events in the agent event stream.
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
        """Calculate current context window utilization."""
        breakdown = {
            "system_prompt": self.estimate_tokens(system_prompt),
            "conversation": sum(self.estimate_tokens(m.content) for m in messages if m.role != "system"),
            "tool_schemas": sum(self.estimate_tokens(str(s)) for s in (tool_schemas or [])),
            "tool_results": sum(
                self.estimate_tokens(m.content)
                for m in messages
                if m.role == "tool"
            ),
            "memory": self.estimate_tokens(memory_context),
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

    def estimate_tokens(self, text: str) -> int:
        """Fast token estimation: ~4 chars per token (good enough for visualization)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def as_hook(self) -> AgentHooks:
        """Returns AgentHooks that emit context_snapshot events after each LLM call."""
        hooks = AgentHooks()

        @hooks.on_after_llm
        def track_context(response):
            # The runtime will call this with the response;
            # actual snapshot happens in the runtime which has access to messages/tools
            if hasattr(response, "usage") and response.usage:
                # Store usage data for the event stream to pick up
                response.metadata["context_tracker"] = self

        return hooks

    def to_event(self) -> AgentEvent:
        """Create an AgentEvent from the latest snapshot."""
        if not self.snapshots:
            return AgentEvent(type="context_snapshot", message="No snapshots", payload={})
        return AgentEvent(
            type="context_snapshot",
            message=f"Context: {self.snapshots[-1].total_tokens}/{self.max_tokens} tokens ({self.snapshots[-1].utilization:.0%})",
            payload=self.snapshots[-1].to_dict(),
        )
```

**New EventType:** Add `context_snapshot` to the EventType literal.

**Runtime integration:** After each LLM call in `AgentRuntime`, if a `ContextTracker` is attached, emit a `context_snapshot` event in the stream.

**Public API additions:**
- `ContextTracker`, `ContextSnapshot`

### 4.2 Backend — Integration into existing views

No new Django app needed. Add context tracking to:
- Agent run/stream views
- Deep agent run/stream views
- Session send/stream views

The `context_snapshot` event naturally flows through the existing event stream. Also store it in TraceEvent for historical analysis.

### 4.3 Frontend — `components/ContextWindowBar.tsx`

**Reusable component:**

```
Props:
  snapshot: ContextSnapshot | null
  compact?: boolean  (for inline use in headers)

Full view:
┌─────────────────────────────────────────────────────────────┐
│ Context Window: 47,231 / 128,000 tokens (37%)               │
│ ████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│                                                              │
│ ▼ Breakdown                                                  │
│ ├── System prompt:    2,100 tokens  ██                (4%)   │
│ ├── Conversation:     8,400 tokens  ████              (18%)  │
│ ├── Tool schemas:     6,200 tokens  ███               (13%)  │
│ ├── Tool results:    22,100 tokens  ███████████       (47%)  │
│ └── Memory context:   8,431 tokens  ████              (18%)  │
│                                                              │
│ ⚠ Compaction triggers at 96,000 tokens (75%)                │
└─────────────────────────────────────────────────────────────┘

Compact view (for headers):
│ ████████████████░░░░░░░░ 37% (47K / 128K)                   │

Colors:
  system_prompt  → blue-500
  conversation   → green-500
  tool_schemas   → amber-500
  tool_results   → orange-500
  memory         → purple-500
  empty          → gray-200

Warning states:
  < 50%  → green indicator
  50-75% → amber indicator
  > 75%  → red indicator + "Compaction imminent" warning
```

**Used in:**
- `SessionChatPage.tsx` — top of chat, live-updates during streaming
- Agent run panels (ToolBuilderPage test panel, AgentDetailPage run panel)
- `DeepAgentStudioPage.tsx` — run output area
- `TraceDetailPage.tsx` — historical snapshot from trace events

---

## Sidebar Navigation Updates

Add new sections to the existing sidebar:

```
Existing:
  Dashboard
  Tools
  Agents
  Deep Agents
  MCP Servers
  Knowledge Base
  Traces

New additions:
  Sessions       ← NEW (chat bubble icon)
  Schedules      ← NEW (clock icon)
  Webhooks       ← NEW (webhook/lightning icon)

  Settings
  ...
```

---

## New Routes Summary

```
/sessions                → SessionListPage
/sessions/:id            → SessionChatPage
/schedules               → ScheduleListPage
/schedules/new           → ScheduleBuilderPage
/schedules/:id           → ScheduleDetailPage
/webhooks                → WebhookListPage
/webhooks/new            → WebhookBuilderPage
/webhooks/:id            → WebhookDetailPage
```

---

## Agent Lib Changes Summary

| Module | Type | Description |
|---|---|---|
| `shipit_agent/schedule.py` | NEW | ScheduleRunner, ScheduleResult |
| `shipit_agent/session_manager.py` | NEW | SessionManager with create/resume/fork/archive |
| `shipit_agent/context_tracker.py` | NEW | ContextTracker, ContextSnapshot |
| `shipit_agent/templates.py` | NEW | PromptTemplate for {variable} rendering |
| `shipit_agent/tools/webhook_payload.py` | NEW | WebhookPayloadTool |
| `shipit_agent/models.py` | MODIFY | Add `context_snapshot` to EventType |
| `shipit_agent/stores/session.py` | MODIFY | Add `list_all()` to session stores |
| `shipit_agent/__init__.py` | MODIFY | Export new public API |

---

## Backend Apps Summary

| App | Models | Views | Celery Tasks |
|---|---|---|---|
| `apps/schedules/` | AgentSchedule, ScheduleRun | list_create, detail, toggle, run_now, runs | run_scheduled_agent |
| `apps/webhooks/` | Webhook, WebhookDelivery | list_create, detail, toggle, trigger, test, deliveries, regenerate_secret | run_webhook_agent |
| `apps/sessions/` | AgentSession | list_create, detail, send, stream, fork, archive, messages | — |

---

## Frontend Summary

| Feature Dir | Pages | API Client | Components |
|---|---|---|---|
| `features/schedules/` | ScheduleListPage, ScheduleBuilderPage, ScheduleDetailPage | `api/schedules.ts` | CronBuilder (inline) |
| `features/webhooks/` | WebhookListPage, WebhookBuilderPage, WebhookDetailPage | `api/webhooks.ts` | SecretDisplay, cURL example (inline) |
| `features/sessions/` | SessionListPage, SessionChatPage | `api/sessions.ts` | MessageBubble, ToolCallCard, TypingIndicator (inline) |
| `components/` | — | — | ContextWindowBar.tsx |

---

## Data Isolation

All new models have `owner = FK(User)`. All views filter by `owner=request.user`. Webhook trigger endpoint is the only exception — it uses HMAC auth instead of JWT, but the webhook itself is owner-scoped.

---

## Dependencies

**Backend (new pip packages):**
- `celery` — task queue
- `django-celery-beat` — DB-backed periodic tasks
- `redis` — celery broker (already in Docker Compose)

**Frontend (no new packages):**
- Uses existing Tailwind, React, TypeScript
- SSE via native EventSource API (already used for agent streaming)
