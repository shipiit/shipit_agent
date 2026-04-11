# SHIPIT Agent Cloud Platform — Full Design Spec

**Date:** 2026-04-10
**Status:** Draft — Design Only (Implementation Later)
**Stack:** React + Vite + TypeScript + Tailwind CSS (Frontend) | Django + DRF (Backend) | shipit_agent (Agent Engine)

---

## Vision

A cloud platform where users build, test, and deploy powerful AI agents visually. Create tools, compose agents, wire MCP servers, run deep agents — all from a browser. More powerful than LangChain/LangSmith, with real-time streaming, traces, and one-click MCP export.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│          React + Vite + TypeScript + Tailwind CSS                │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │  Tool    │ │  Agent   │ │   Deep   │ │  Traces  │          │
│  │ Builder  │ │ Builder  │ │  Agent   │ │  & Logs  │          │
│  │          │ │          │ │  Studio  │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ MCP      │ │ Knowledge│ │ Settings │ │ Billing  │          │
│  │ Manager  │ │  Base    │ │ & Auth   │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└───────────────────────┬─────────────────────────────────────────┘
                        │ REST + WebSocket
┌───────────────────────▼─────────────────────────────────────────┐
│                        BACKEND                                   │
│              Django + Django REST Framework                       │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Auth     │ │ Tool     │ │ Agent    │ │ Trace    │          │
│  │ Service  │ │ Service  │ │ Service  │ │ Service  │          │
│  │ (SSO)    │ │          │ │          │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│  │ MCP      │ │ Memory   │ │ Billing  │                       │
│  │ Service  │ │ Service  │ │ Service  │                       │
│  └──────────┘ └──────────┘ └──────────┘                       │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                    AGENT ENGINE                                  │
│                   shipit_agent lib                                │
│                                                                  │
│  Agent, GoalAgent, ReflectiveAgent, Supervisor, Pipeline,        │
│  AgentTeam, Memory, Parsers, Tools, MCP, Streaming               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Sub-Project Breakdown

### Sub-Project 1: API Server + Auth

**Backend foundation that powers everything.**

#### 1.1 Django Project Structure

```
shipit_cloud/
├── manage.py
├── shipit_cloud/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py              # WebSocket support
├── apps/
│   ├── auth_app/             # SSO, Google, GitHub login
│   │   ├── models.py         # User, Organization, APIKey
│   │   ├── views/            # Split API views by concern
│   │   │   ├── auth.py
│   │   │   └── api_keys.py
│   │   ├── serializers.py
│   │   └── urls.py
│   ├── tools/                # Tool CRUD
│   │   ├── models.py         # Tool, ToolVersion, ToolTestRun
│   │   ├── views/
│   │   │   ├── list_create.py
│   │   │   ├── detail.py
│   │   │   ├── test.py
│   │   │   └── runs.py
│   │   ├── serializers.py
│   │   └── urls.py
│   ├── agents/               # Agent CRUD
│   │   ├── models.py         # Agent, AgentConfig, AgentRun
│   │   ├── views/
│   │   │   ├── list_create.py
│   │   │   ├── detail.py
│   │   │   └── run.py
│   │   ├── serializers.py
│   │   ├── consumers.py      # WebSocket for streaming
│   │   └── urls.py
│   ├── deep_agents/          # Deep Agent management
│   │   ├── models.py         # DeepAgent, Goal, Worker, Team
│   │   ├── views/
│   │   │   ├── list_create.py
│   │   │   ├── detail.py
│   │   │   ├── run.py
│   │   │   └── traces.py
│   │   ├── consumers.py      # WebSocket streaming
│   │   └── urls.py
│   ├── mcp_manager/          # MCP server connections
│   │   ├── models.py         # MCPConnection, MCPTool
│   │   ├── views/
│   │   │   ├── list.py
│   │   │   ├── connect.py
│   │   │   ├── detail.py
│   │   │   ├── tools.py
│   │   │   └── test.py
│   │   └── urls.py
│   ├── memory/               # Knowledge base & memory
│   │   ├── models.py         # MemoryStore, Fact, Entity
│   │   ├── views.py          # Add, search, manage
│   │   └── urls.py
│   ├── traces/               # Execution traces & logs
│   │   ├── models.py         # Trace, TraceEvent, TraceStep
│   │   ├── views.py          # View, filter, export
│   │   └── urls.py
│   ├── billing/              # Paid tiers
│   │   ├── models.py         # Plan, Subscription, Usage
│   │   ├── views.py
│   │   └── urls.py
│   └── export/               # Agent-to-MCP exporter
│       ├── views.py          # Convert agent to MCP server
│       └── urls.py
├── requirements.txt
└── docker-compose.yml
```

#### 1.2 Auth System

```
Authentication Methods:
├── Email + Password (Django built-in)
├── Google OAuth 2.0 (django-allauth)
├── GitHub OAuth (django-allauth)
└── API Keys (for programmatic access)

Models:
├── User
│   ├── email, name, avatar
│   ├── auth_provider: "email" | "google" | "github"
│   ├── organization: FK -> Organization
│   ├── plan: "free" | "pro" | "enterprise"
│   └── api_keys: [APIKey]
├── Organization
│   ├── name, slug
│   ├── members: [User]
│   └── settings: JSON
└── APIKey
    ├── key_hash, name, scopes
    ├── created_at, last_used_at
    └── is_active
```

#### 1.2.1 API Documentation Standard

All REST endpoints should be documented with `drf_yasg` and explicitly annotated using:

```python
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
```

Rules:

- Every API view method gets `@swagger_auto_schema`
- Request bodies should use serializers when possible
- Manual `openapi.Schema(...)` definitions are acceptable for simple POST payloads
- Swagger UI and ReDoc should be mounted from the Django project root
- Feature apps should keep views in a `views/` package, not a single large `views.py`

This keeps the backend readable as the platform grows and prevents feature apps from collapsing into one-file API modules.

#### 1.3 API Endpoints

```
Authentication:
  POST   /api/auth/register/
  POST   /api/auth/login/
  POST   /api/auth/logout/
  GET    /api/auth/me/
  GET    /api/auth/google/
  GET    /api/auth/github/
  POST   /api/auth/api-keys/
  DELETE /api/auth/api-keys/{id}/

Tools:
  GET    /api/tools/                    # list user's tools
  POST   /api/tools/                    # create tool
  GET    /api/tools/{id}/               # get tool detail
  PUT    /api/tools/{id}/               # update tool
  DELETE /api/tools/{id}/               # delete tool
  POST   /api/tools/{id}/test/          # test tool with sample input
  GET    /api/tools/{id}/runs/          # test run history

Agents:
  GET    /api/agents/                   # list agents
  POST   /api/agents/                   # create agent
  GET    /api/agents/{id}/              # get agent detail
  PUT    /api/agents/{id}/              # update agent config
  DELETE /api/agents/{id}/              # delete agent
  POST   /api/agents/{id}/run/          # run agent (returns result)
  WS     /ws/agents/{id}/stream/        # stream agent events

Deep Agents:
  GET    /api/deep-agents/              # list deep agents
  POST   /api/deep-agents/             # create deep agent
  GET    /api/deep-agents/{id}/         # get detail
  PUT    /api/deep-agents/{id}/         # update config
  POST   /api/deep-agents/{id}/run/     # run
  WS     /ws/deep-agents/{id}/stream/   # stream events
  GET    /api/deep-agents/{id}/traces/  # execution traces

MCP:
  GET    /api/mcp/                      # list MCP connections
  POST   /api/mcp/connect/             # connect to MCP server
  GET    /api/mcp/{id}/tools/           # discover tools from MCP
  POST   /api/mcp/{id}/test/            # test MCP connection
  DELETE /api/mcp/{id}/                 # disconnect

Memory:
  GET    /api/memory/                   # list memory stores
  POST   /api/memory/                   # create memory store
  POST   /api/memory/{id}/facts/        # add facts
  GET    /api/memory/{id}/search/       # search memory
  GET    /api/memory/{id}/entities/     # list entities
  POST   /api/memory/{id}/entities/     # add entity

Traces:
  GET    /api/traces/                   # list traces
  GET    /api/traces/{id}/              # get trace detail
  GET    /api/traces/{id}/events/       # get trace events
  GET    /api/traces/{id}/export/       # export trace as JSON

Export:
  POST   /api/export/mcp/              # convert agent to MCP server
  GET    /api/export/mcp/{id}/          # get MCP server config
  GET    /api/export/mcp/{id}/code/     # download MCP server code

Settings:
  GET    /api/settings/                 # user settings
  PUT    /api/settings/                 # update settings
  GET    /api/settings/providers/       # list LLM providers
  POST   /api/settings/providers/       # set default provider + model
  POST   /api/settings/providers/test/  # test provider connection

Billing:
  GET    /api/billing/plan/             # current plan
  POST   /api/billing/upgrade/          # upgrade plan
  GET    /api/billing/usage/            # usage stats
```

---

### Sub-Project 2: Frontend — React + Vite + TypeScript + Tailwind

#### 2.1 Project Structure

```
shipit_ui/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── router.tsx                    # React Router
│   ├── api/
│   │   ├── client.ts                # Axios/fetch wrapper
│   │   ├── auth.ts                  # Auth API calls
│   │   ├── tools.ts                 # Tool API calls
│   │   ├── agents.ts                # Agent API calls
│   │   ├── deep-agents.ts           # Deep Agent API calls
│   │   ├── mcp.ts                   # MCP API calls
│   │   ├── memory.ts                # Memory API calls
│   │   ├── traces.ts                # Traces API calls
│   │   └── websocket.ts             # WebSocket streaming
│   ├── stores/
│   │   ├── auth.ts                  # Zustand auth store
│   │   ├── tools.ts
│   │   ├── agents.ts
│   │   └── ui.ts                    # Theme, sidebar state
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx         # Main layout with sidebar
│   │   │   ├── Sidebar.tsx          # Navigation sidebar
│   │   │   ├── Header.tsx           # Top bar with user menu
│   │   │   └── BreadCrumbs.tsx
│   │   ├── auth/
│   │   │   ├── LoginPage.tsx
│   │   │   ├── RegisterPage.tsx
│   │   │   ├── GoogleLoginButton.tsx
│   │   │   └── GitHubLoginButton.tsx
│   │   ├── tools/
│   │   │   ├── ToolListPage.tsx
│   │   │   ├── ToolBuilderPage.tsx  # Create/edit tool
│   │   │   ├── ToolTestPanel.tsx    # Test tool with inputs
│   │   │   ├── ToolSchemaEditor.tsx # JSON schema editor
│   │   │   └── ToolCard.tsx
│   │   ├── agents/
│   │   │   ├── AgentListPage.tsx
│   │   │   ├── AgentBuilderPage.tsx # Create/edit agent
│   │   │   ├── AgentRunPage.tsx     # Run + stream output
│   │   │   ├── ToolSelector.tsx     # Pick tools for agent
│   │   │   ├── MCPSelector.tsx      # Pick MCP servers
│   │   │   ├── MemorySelector.tsx   # Pick memory store
│   │   │   ├── PromptEditor.tsx     # System prompt editor
│   │   │   └── AgentCard.tsx
│   │   ├── deep-agents/
│   │   │   ├── DeepAgentListPage.tsx
│   │   │   ├── DeepAgentStudio.tsx  # Visual deep agent builder
│   │   │   ├── GoalAgentBuilder.tsx
│   │   │   ├── SupervisorBuilder.tsx
│   │   │   ├── ReflectiveBuilder.tsx
│   │   │   ├── AgentLinker.tsx      # Link multiple agents
│   │   │   ├── StreamingOutput.tsx  # Real-time event stream
│   │   │   └── DeepAgentCard.tsx
│   │   ├── mcp/
│   │   │   ├── MCPListPage.tsx
│   │   │   ├── MCPConnectPage.tsx   # Connect to MCP server
│   │   │   ├── MCPToolDiscovery.tsx # Discover tools from MCP
│   │   │   └── MCPCard.tsx
│   │   ├── memory/
│   │   │   ├── MemoryListPage.tsx
│   │   │   ├── MemoryExplorer.tsx   # Browse facts, entities
│   │   │   ├── KnowledgeBase.tsx    # Upload docs, add facts
│   │   │   └── EntityGraph.tsx      # Visual entity relationships
│   │   ├── traces/
│   │   │   ├── TraceListPage.tsx
│   │   │   ├── TraceDetailPage.tsx  # Full trace timeline
│   │   │   ├── TraceEventCard.tsx   # Individual event display
│   │   │   ├── TraceTimeline.tsx    # Visual timeline
│   │   │   └── TraceExport.tsx
│   │   ├── settings/
│   │   │   ├── SettingsPage.tsx
│   │   │   ├── ProviderConfig.tsx   # Set default LLM provider
│   │   │   ├── APIKeyManager.tsx
│   │   │   └── BillingPage.tsx
│   │   ├── export/
│   │   │   ├── ExportMCPPage.tsx    # Convert agent to MCP
│   │   │   └── MCPCodePreview.tsx   # Preview generated code
│   │   └── shared/
│   │       ├── Button.tsx
│   │       ├── Modal.tsx
│   │       ├── JsonEditor.tsx       # Monaco-based JSON editor
│   │       ├── CodeEditor.tsx       # Monaco code editor
│   │       ├── StreamingLog.tsx     # Real-time event log
│   │       ├── StatusBadge.tsx
│   │       └── EmptyState.tsx
│   ├── hooks/
│   │   ├── useWebSocket.ts          # WebSocket streaming hook
│   │   ├── useAgent.ts
│   │   └── useAuth.ts
│   └── types/
│       ├── tool.ts
│       ├── agent.ts
│       ├── deep-agent.ts
│       ├── mcp.ts
│       ├── trace.ts
│       └── user.ts
```

#### 2.2 Pages & Routes

```
/                              → Dashboard (overview stats)
/login                         → Login (email/Google/GitHub)
/register                      → Register

/tools                         → Tool list
/tools/new                     → Tool builder (create)
/tools/:id                     → Tool detail + test panel
/tools/:id/edit                → Tool editor

/agents                        → Agent list
/agents/new                    → Agent builder
/agents/:id                    → Agent detail
/agents/:id/run                → Run agent + streaming output
/agents/:id/edit               → Edit agent config

/deep-agents                   → Deep agent list
/deep-agents/new               → Deep agent studio (create)
/deep-agents/:id               → Deep agent detail + traces
/deep-agents/:id/run           → Run + stream events
/deep-agents/:id/edit          → Edit configuration

/mcp                           → MCP connections list
/mcp/connect                   → Connect new MCP server
/mcp/:id                       → MCP detail + tool discovery

/memory                        → Memory stores list
/memory/:id                    → Memory explorer (facts, entities)
/memory/:id/knowledge          → Knowledge base (upload, add)

/traces                        → Trace list
/traces/:id                    → Trace detail timeline

/settings                      → User settings
/settings/providers            → LLM provider config
/settings/api-keys             → API key management
/settings/billing              → Billing & usage

/export/mcp                    → Agent-to-MCP exporter
```

#### 2.3 Visual System Requirements

The frontend should not look like a generic admin dashboard. It needs an intentional operator-console aesthetic with:

- Support for `light`, `dark`, and `system` theme modes
- Theme mode persisted in the backend, not only local storage
- Typography controls persisted in the backend
- A stronger display font for headers and a separate readable body font
- CSS variable based design tokens so the same components can adapt across theme modes cleanly
- Support for reduced-motion preferences

Recommended persisted UI preference shape:

```json
{
  "theme_mode": "system",
  "accent_color": "#5ae4a8",
  "font_family": "space-grotesk",
  "font_scale": "comfortable",
  "reduce_motion": false,
  "nav_collapsed": false
}
```

Recommended frontend state flow:

1. App boot requests `/api/settings/`
2. Response hydrates a theme store/provider
3. Provider resolves `system` to `light` or `dark` using `prefers-color-scheme`
4. Provider applies `data-theme`, `data-font`, and `data-scale` on `<html>`
5. User changes are persisted immediately with optimistic UI updates

Recommended token groups:

- Surface: app background, panel, elevated panel, border
- Text: primary, muted, inverted
- Accent: primary accent, soft accent wash, success, warning, danger
- Typography: display font, body font, mono font, scale multiplier
- Motion: normal, reduced

This gives the UI a stable system for dashboards, builders, trace viewers, and editors without hard-coding colors per page.

---

### Sub-Project 3: Tool Builder UI

**What the user sees:**

```
┌─────────────────────────────────────────────────────────┐
│ Tool Builder                                    [Save]   │
├────────────────────────┬────────────────────────────────┤
│                        │                                │
│  Tool Name:            │  Test Panel                    │
│  [my_calculator    ]   │                                │
│                        │  Input:                        │
│  Description:          │  ┌──────────────────────┐     │
│  [Calculates math  ]   │  │ {"a": 5, "b": 3}    │     │
│                        │  └──────────────────────┘     │
│  Type:                 │                                │
│  ○ Function Tool       │  [▶ Run Test]                  │
│  ○ Class Tool          │                                │
│  ○ API Connector       │  Output:                       │
│                        │  ┌──────────────────────┐     │
│  Code:                 │  │ {"result": 8}        │     │
│  ┌─────────────────┐   │  └──────────────────────┘     │
│  │ def calculate(  │   │                                │
│  │   a: int,       │   │  Status: ✅ Passed             │
│  │   b: int,       │   │  Time: 0.02s                  │
│  │ ) -> str:       │   │                                │
│  │   return str(   │   │  Test History:                 │
│  │     a + b       │   │  ├── ✅ Test 1 (0.02s)        │
│  │   )             │   │  ├── ✅ Test 2 (0.01s)        │
│  └─────────────────┘   │  └── ❌ Test 3 (0.03s)        │
│                        │                                │
│  Schema:               │                                │
│  ┌─────────────────┐   │                                │
│  │ { "type": ...}  │   │                                │
│  └─────────────────┘   │                                │
│                        │                                │
└────────────────────────┴────────────────────────────────┘
```

---

### Sub-Project 4: Agent Builder UI

**What the user sees:**

```
┌─────────────────────────────────────────────────────────┐
│ Agent Builder                               [Save] [Run]│
├────────────────────────┬────────────────────────────────┤
│ Configuration          │ Preview / Run                   │
│                        │                                │
│ Name: [my-research-bot]│ Prompt:                        │
│                        │ ┌──────────────────────┐      │
│ Provider:              │ │ You are a research   │      │
│ [▾ Bedrock        ]    │ │ expert. Search the   │      │
│                        │ │ web for facts...     │      │
│ Model:                 │ └──────────────────────┘      │
│ [▾ gpt-oss-120b   ]    │                                │
│                        │ Test Input:                    │
│ Max Iterations: [4]    │ ┌──────────────────────┐      │
│ Parallel Tools: [✓]    │ │ Research Python 3.13 │      │
│                        │ └──────────────────────┘      │
│ ── Tools ───────────── │                                │
│ [✓] web_search         │ [▶ Run Agent]                  │
│ [✓] open_url           │                                │
│ [✓] code_execution     │ ── Streaming Output ────────── │
│ [ ] memory             │ 🚀 Agent run started           │
│ [✓] my_calculator      │ ▶️ LLM completion started      │
│ [+] Add custom tool    │ 🔧 Tool called: web_search     │
│                        │ 📦 Tool completed: web_search  │
│ ── MCP Servers ─────── │ ────────────────────────────── │
│ [✓] GitHub MCP         │ Python 3.13 was released on    │
│ [✓] Figma MCP          │ October 2025 with several key  │
│ [+] Connect MCP        │ new features including...      │
│                        │ ────────────────────────────── │
│ ── Memory ──────────── │ ✅ Agent run completed          │
│ [✓] Research Memory    │                                │
│ [+] Create Memory      │ Tokens: 1,247 | Time: 3.2s    │
│                        │                                │
└────────────────────────┴────────────────────────────────┘
```

---

### Sub-Project 5: Deep Agent Studio UI

**What the user sees:**

```
┌─────────────────────────────────────────────────────────┐
│ Deep Agent Studio                       [Save] [▶ Run]  │
├─────────────┬───────────────────────────────────────────┤
│ Agent Type  │                                           │
│             │ ┌─────────────────────────────────────┐   │
│ ○ GoalAgent │ │         VISUAL WORKFLOW              │   │
│ ● Supervisor│ │                                     │   │
│ ○ Reflective│ │  ┌──────────┐    ┌──────────┐     │   │
│ ○ Pipeline  │ │  │Researcher│───▶│  Writer  │     │   │
│ ○ Team      │ │  │  Agent   │    │  Agent   │     │   │
│             │ │  └──────────┘    └────┬─────┘     │   │
│ ── Config ──│ │                       │           │   │
│             │ │                  ┌────▼─────┐     │   │
│ Workers:    │ │                  │ Reviewer │     │   │
│ [+ Add]     │ │                  │  Agent   │     │   │
│             │ │                  └──────────┘     │   │
│ researcher  │ │                                     │   │
│  └ Tools: 5 │ │  Supervisor LLM: Bedrock gpt-oss   │   │
│  └ MCP: 1   │ │  Max delegations: 6                 │   │
│             │ └─────────────────────────────────────┘   │
│ writer      │                                           │
│  └ Tools: 0 │ ── Live Execution Log ────────────────── │
│  └ Prompt:..│                                           │
│             │ 🚀 Supervisor started                     │
│ reviewer    │ 📋 Round 1: Deciding next step...         │
│  └ Tools: 0 │ 🔧 [researcher] Delegating: "Research AI"│
│             │ 📦 [researcher] Done                      │
│ ── Memory ──│ ────────────────────────────────────────  │
│ [✓] Shared  │ Python's growth in 2025 continues to     │
│             │ accelerate, driven by AI/ML adoption...   │
│ ── Goal ──  │ ────────────────────────────────────────  │
│ (GoalAgent) │ 📋 Round 2: Deciding next step...         │
│ Objective:  │ 🔧 [writer] Delegating: "Write summary"  │
│ [.......  ] │ 📦 [writer] Done                          │
│ Criteria:   │ ────────────────────────────────────────  │
│ [+ Add]     │ The landscape of Python development...   │
│             │ ────────────────────────────────────────  │
│             │ ✅ Supervisor completed (2 rounds)         │
│             │                                           │
│             │ Tokens: 3,847 | Time: 8.1s | Rounds: 2   │
└─────────────┴───────────────────────────────────────────┘
```

---

### Sub-Project 6: Trace Viewer UI

```

---

## Backend Implementation Notes Added For UI Persistence

To support a modern theme/font system properly, the backend should store UI preferences per user or per workspace member.

### Recommended Model

```
UserPreference
├── user: OneToOne(User)
├── theme_mode: "light" | "dark" | "system"
├── accent_color: string
├── font_family: "space-grotesk" | "ibm-plex-sans" | "source-serif-4"
├── font_scale: "compact" | "comfortable" | "large"
├── reduce_motion: bool
├── nav_collapsed: bool
└── updated_at
```

### Recommended Endpoints

```
GET /api/settings/            # fetch persisted UI preferences
PUT /api/settings/            # update theme/font/layout preferences
```

### Backend Behavior

- Return a default preference object for new users automatically
- Store the selected theme mode, not only the resolved mode
- Let the frontend resolve `system` on the client via media query
- Keep settings lightweight and fast because they are loaded at app startup
- Extend the same settings object later with editor preferences, default model, preferred trace density, and preferred dashboard layout

---

## Suggested Initial Build Order

For implementation, the fastest path is:

1. Backend foundation
   - Django project
   - DRF setup
   - health endpoint
   - settings/preferences endpoint
2. Frontend shell
   - router
   - app shell
   - dashboard
   - settings page
   - theme/font provider
3. Agent and tool modules
   - read-only lists first
   - builders second
   - run/stream pages third
4. Streaming and trace viewer
   - WebSocket event transport
   - timeline/event cards
5. Auth and billing hardening

This order gets a polished usable shell online early, while keeping the more complex agent execution and streaming work behind a stable UI/backend contract.
┌─────────────────────────────────────────────────────────┐
│ Trace: supervisor-run-abc123          [Export JSON]      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Timeline                                                │
│ ──────                                                  │
│ 0.0s  🚀 run_started                                    │
│ 0.1s  📋 planning_started — Round 1                     │
│ 0.8s  🔧 tool_called — [researcher] "Research AI"       │
│ 1.2s  │  🔧 web_search("AI trends 2025")               │
│ 2.1s  │  📦 web_search returned (3 results)             │
│ 3.4s  📦 tool_completed — [researcher]                  │
│ 3.5s  📋 planning_started — Round 2                     │
│ 4.2s  🔧 tool_called — [writer] "Write summary"        │
│ 5.8s  📦 tool_completed — [writer]                      │
│ 5.9s  ✅ run_completed                                   │
│                                                         │
│ ── Event Detail (click any event above) ──────────────  │
│                                                         │
│ Type: tool_completed                                    │
│ Worker: researcher                                      │
│ Duration: 2.6s                                          │
│ Output:                                                 │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ AI adoption in enterprises grew 35% in 2025.       │ │
│ │ Key drivers: customer service automation (42%),     │ │
│ │ code generation (38%), data analysis (31%).         │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Metadata:                                               │
│   tokens_used: 847                                      │
│   tools_called: ["web_search"]                          │
│   model: bedrock/openai.gpt-oss-120b                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### Sub-Project 7: Knowledge Base & Memory UI

```
┌─────────────────────────────────────────────────────────┐
│ Knowledge Base: "Product Research"         [+ Add Fact] │
├───────────────┬─────────────────────────────────────────┤
│ Sources       │ Facts (23 items)                        │
│               │                                         │
│ ── Facts ──── │ ┌─────────────────────────────────────┐ │
│ 23 items      │ │ Python 3.13 released Oct 2025      │ │
│               │ │ Category: technology                │ │
│ ── Entities ──│ │ Added: 2 hours ago                  │ │
│ 8 tracked     │ └─────────────────────────────────────┘ │
│               │ ┌─────────────────────────────────────┐ │
│ ── Search ──  │ │ SHIPIT Agent supports 10 providers │ │
│ [Search...]   │ │ Category: product                   │ │
│               │ │ Added: 1 day ago                    │ │
│               │ └─────────────────────────────────────┘ │
│ ── Upload ──  │                                         │
│ [📄 Upload    │ Entities (8 tracked)                    │
│  documents]   │                                         │
│               │ ┌─────────────────────────────────────┐ │
│ Supported:    │ │ 👤 Alice — CTO, works on Atlas     │ │
│ • PDF         │ │ 📁 Project Atlas — K8s migration   │ │
│ • TXT         │ │ 🔧 SHIPIT Agent — agent framework  │ │
│ • CSV         │ └─────────────────────────────────────┘ │
│ • Markdown    │                                         │
└───────────────┴─────────────────────────────────────────┘
```

---

### Sub-Project 8: Agent-to-MCP Exporter

**Convert any agent or deep agent into an MCP server that others can use.**

```
┌─────────────────────────────────────────────────────────┐
│ Export Agent as MCP Server                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Select Agent:                                           │
│ [▾ my-research-bot (Agent)                          ]   │
│                                                         │
│ MCP Server Name: [research-bot-mcp]                     │
│                                                         │
│ Transport:                                              │
│ ○ HTTP (remote, any client)                             │
│ ● Stdio (local subprocess)                              │
│                                                         │
│ Exposed Tools:                                          │
│ [✓] research — "Search and summarize a topic"           │
│ [✓] analyze — "Analyze data with code execution"        │
│ [ ] raw_run — "Run arbitrary prompt"                    │
│                                                         │
│ [Generate MCP Server]                                   │
│                                                         │
│ ── Generated Code ──────────────────────────────────── │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ # Auto-generated MCP server for my-research-bot    │ │
│ │ from shipit_agent.mcp import MCPServer, MCPTool     │ │
│ │ from shipit_agent import Agent                      │ │
│ │                                                     │ │
│ │ agent = Agent(llm=llm, tools=[...], prompt="...")   │ │
│ │ server = MCPServer(name="research-bot-mcp")         │ │
│ │ server.register(MCPTool(                            │ │
│ │     name="research",                                │ │
│ │     handler=lambda q: agent.run(q).output,          │ │
│ │ ))                                                  │ │
│ │ server.serve()                                      │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ [📋 Copy Code] [💾 Download] [🚀 Deploy]                │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Data Models (Django)

### Tool Model

```python
class Tool(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField()
    tool_type = models.CharField(choices=[("function", "Function"), ("class", "Class"), ("api", "API")])
    code = models.TextField()
    schema = models.JSONField()
    prompt_instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Agent Model

```python
class AgentConfig(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    system_prompt = models.TextField()
    provider = models.CharField(max_length=50)  # "bedrock", "openai", etc.
    model = models.CharField(max_length=100)
    max_iterations = models.IntegerField(default=4)
    parallel_tools = models.BooleanField(default=False)
    tools = models.ManyToManyField(Tool, blank=True)
    mcp_connections = models.ManyToManyField("MCPConnection", blank=True)
    memory_store = models.ForeignKey("MemoryStoreConfig", null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Deep Agent Model

```python
class DeepAgentConfig(models.Model):
    AGENT_TYPES = [
        ("goal", "GoalAgent"),
        ("reflective", "ReflectiveAgent"),
        ("supervisor", "Supervisor"),
        ("adaptive", "AdaptiveAgent"),
        ("pipeline", "Pipeline"),
        ("team", "AgentTeam"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    agent_type = models.CharField(choices=AGENT_TYPES)
    config = models.JSONField()  # type-specific config
    linked_agents = models.ManyToManyField(AgentConfig, blank=True)
    memory_store = models.ForeignKey("MemoryStoreConfig", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Trace Model

```python
class Trace(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    agent = models.ForeignKey(AgentConfig, null=True, on_delete=models.SET_NULL)
    deep_agent = models.ForeignKey(DeepAgentConfig, null=True, on_delete=models.SET_NULL)
    trace_id = models.UUIDField(unique=True)
    status = models.CharField(choices=[("running", "Running"), ("completed", "Completed"), ("failed", "Failed")])
    input_prompt = models.TextField()
    output = models.TextField(blank=True)
    total_tokens = models.IntegerField(default=0)
    duration_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class TraceEvent(models.Model):
    trace = models.ForeignKey(Trace, related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50)
    message = models.TextField()
    payload = models.JSONField()
    timestamp = models.DateTimeField(auto_now_add=True)
```

---

## Tech Stack Summary

| Layer            | Technology              | Why                               |
| ---------------- | ----------------------- | --------------------------------- |
| **Frontend**     | React 18 + Vite 5       | Fast dev, HMR, modern             |
| **Language**     | TypeScript              | Type safety                       |
| **Styling**      | Tailwind CSS            | Utility-first, fast               |
| **State**        | Zustand                 | Simple, minimal boilerplate       |
| **Code Editor**  | Monaco Editor           | VS Code-quality editing           |
| **Backend**      | Django 5 + DRF          | Mature, batteries-included        |
| **WebSocket**    | Django Channels         | Real-time streaming               |
| **Auth**         | django-allauth          | Google, GitHub, email SSO         |
| **Database**     | PostgreSQL              | Production-ready                  |
| **Cache**        | Redis                   | WebSocket channel layer + caching |
| **Agent Engine** | shipit_agent            | Our library                       |
| **Deployment**   | Docker + Docker Compose | Easy self-hosting                 |

---

## Build Order

| Phase       | What                                                   | Duration  |
| ----------- | ------------------------------------------------------ | --------- |
| **Phase 1** | Django API + Auth (SSO, Google, GitHub) + basic models | Week 1-2  |
| **Phase 2** | React app shell + routing + auth pages + settings      | Week 2-3  |
| **Phase 3** | Tool Builder UI + API                                  | Week 3-4  |
| **Phase 4** | Agent Builder UI + streaming + API                     | Week 4-5  |
| **Phase 5** | Deep Agent Studio + traces                             | Week 5-7  |
| **Phase 6** | Knowledge Base + Memory UI                             | Week 7-8  |
| **Phase 7** | MCP Manager + Agent-to-MCP exporter                    | Week 8-9  |
| **Phase 8** | Billing + polish + deployment                          | Week 9-10 |

---

## Pricing, Plans & Token Usage

### Plans

| Feature | Free | Pro ($29/mo) | Team ($79/mo) | Enterprise (Custom) |
|---|---|---|---|---|
| **Token budget** | 100K tokens/mo | 5M tokens/mo | 25M tokens/mo | Unlimited |
| **Agents** | 3 | 25 | Unlimited | Unlimited |
| **Deep agents** | 1 | 10 | Unlimited | Unlimited |
| **Tools** | 5 | 50 | Unlimited | Unlimited |
| **MCP connections** | 1 | 10 | Unlimited | Unlimited |
| **Memory stores** | 1 (100 facts) | 10 (10K facts) | Unlimited | Unlimited |
| **Knowledge base** | 5 docs | 500 docs | Unlimited | Unlimited |
| **Trace retention** | 24 hours | 30 days | 90 days | Custom |
| **Max iterations/run** | 4 | 10 | 20 | Custom |
| **Parallel tools** | No | Yes | Yes | Yes |
| **Streaming** | Yes | Yes | Yes | Yes |
| **Agent-to-MCP export** | No | Yes | Yes | Yes |
| **Team members** | 1 | 1 | 10 | Unlimited |
| **SSO (Google/GitHub)** | Yes | Yes | Yes | Yes + SAML |
| **API access** | Rate limited | Yes | Yes | Yes |
| **Priority support** | No | Email | Email + chat | Dedicated |
| **Self-hosting** | No | No | Yes | Yes |
| **SLA** | No | No | 99.9% | 99.99% |

### Token Tracking

Every LLM call is tracked at the API level. The system records prompt tokens, completion tokens, and total tokens per request.

```python
# Django model
class TokenUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    trace = models.ForeignKey(Trace, null=True, on_delete=models.SET_NULL)
    agent = models.ForeignKey(AgentConfig, null=True, on_delete=models.SET_NULL)
    provider = models.CharField(max_length=50)       # "bedrock", "openai", etc.
    model = models.CharField(max_length=100)          # "gpt-oss-120b", etc.
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class MonthlyUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    month = models.DateField()                        # first of month
    total_tokens = models.BigIntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    agent_runs = models.IntegerField(default=0)
    deep_agent_runs = models.IntegerField(default=0)
    tools_created = models.IntegerField(default=0)
```

### Token Budget Enforcement

When users approach or exceed their token budget:

```
Usage Lifecycle:
─────────────────────────────────────────────────
0%          50%         75%         90%    100%
│           │           │           │       │
│           │           │     ┌─────┴───┐   │
│           │           │     │ Warning │   │
│           │           │     │ banner  │   │
│           │           │     └─────────┘   │
│           │     ┌─────┴───────┐           │
│           │     │ Email alert │           │
│           │     │ "75% used"  │           │
│           │     └─────────────┘           │
│           │                         ┌─────┴───────────┐
│           │                         │ SOFT LIMIT       │
│           │                         │ - Agents throttled│
│           │                         │ - Max 2 iter/run │
│           │                         │ - No deep agents │
│           │                         │ - Upgrade banner │
│           │                         └─────────────────┘
│           │                                       │
│           │                                 ┌─────┴───────────┐
│           │                                 │ HARD LIMIT       │
│           │                                 │ - Agent runs     │
│           │                                 │   blocked        │
│           │                                 │ - Read-only mode │
│           │                                 │ - Must upgrade   │
│           │                                 │   or wait reset  │
│           │                                 └─────────────────┘
```

#### Enforcement rules

| Usage level | What happens |
|---|---|
| **0-75%** | Normal operation, no restrictions |
| **75%** | Email notification: "You've used 75% of your monthly tokens" |
| **90%** | Warning banner in UI: "Running low on tokens — 10% remaining" |
| **95%** | Soft limit — agents throttled to max 2 iterations per run, deep agents disabled, upgrade prompt shown |
| **100%** | Hard limit — agent runs blocked, read-only mode, must upgrade or wait for monthly reset |

#### API enforcement

```python
# Django middleware
class TokenBudgetMiddleware:
    def process_request(self, request):
        user = request.user
        usage = get_monthly_usage(user)
        plan = user.plan

        budget = PLAN_BUDGETS[plan.name]  # e.g. 5_000_000 for Pro

        if usage.total_tokens >= budget:
            return JsonResponse({
                "error": "token_budget_exceeded",
                "message": "Monthly token budget exceeded. Upgrade your plan or wait for reset.",
                "usage": usage.total_tokens,
                "budget": budget,
                "resets_at": get_next_reset_date(),
                "upgrade_url": "/settings/billing",
            }, status=429)

        if usage.total_tokens >= budget * 0.95:
            # Soft limit — inject restrictions
            request.token_restrictions = {
                "max_iterations": 2,
                "deep_agents_allowed": False,
                "parallel_tools": False,
            }
```

### Usage Dashboard

```
┌─────────────────────────────────────────────────────────┐
│ Usage — April 2026                          Pro Plan     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Token Usage                                             │
│ ████████████████████░░░░░░░░░░  2.1M / 5M (42%)       │
│                                                         │
│ ┌─────────────────────────────────────────────────┐     │
│ │ Daily Usage (tokens)                            │     │
│ │                                                 │     │
│ │     ▄                                           │     │
│ │    ▄█     ▄                                     │     │
│ │   ▄██    ▄█▄   ▄                                │     │
│ │  ▄███   ▄███  ▄█▄  ▄                            │     │
│ │ ▄████  ▄████ ▄███ ▄█▄                           │     │
│ │ █████ ██████ ████ ███                            │     │
│ │ Apr 1  Apr 5  Apr 10  Apr 15                    │     │
│ └─────────────────────────────────────────────────┘     │
│                                                         │
│ Breakdown                                               │
│ ├── Agent runs:       847 runs (1.2M tokens)           │
│ ├── Deep agent runs:   23 runs (0.6M tokens)           │
│ ├── Tool tests:       156 runs (0.1M tokens)           │
│ └── Benchmarks:        12 runs (0.2M tokens)           │
│                                                         │
│ By Provider                                             │
│ ├── Bedrock gpt-oss:  1.5M tokens ($0.42)              │
│ ├── OpenAI gpt-4o:    0.4M tokens ($1.20)              │
│ └── Anthropic Claude: 0.2M tokens ($0.80)              │
│                                                         │
│ Estimated Cost: $2.42 this month                        │
│                                                         │
│ [View detailed logs]  [Export CSV]  [Upgrade plan]      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Cost Estimation per Provider

| Provider | Model | Input (per 1M) | Output (per 1M) |
|---|---|---|---|
| AWS Bedrock | gpt-oss-120b | $0.18 | $0.54 |
| AWS Bedrock | Claude Sonnet | $3.00 | $15.00 |
| OpenAI | gpt-4o-mini | $0.15 | $0.60 |
| OpenAI | gpt-4o | $2.50 | $10.00 |
| OpenAI | o3-mini | $1.10 | $4.40 |
| Anthropic | Claude Haiku | $0.25 | $1.25 |
| Anthropic | Claude Sonnet | $3.00 | $15.00 |
| Anthropic | Claude Opus | $15.00 | $75.00 |
| Groq | Llama 3.3 70B | $0.59 | $0.79 |
| Together | Llama 3.1 70B | $0.88 | $0.88 |

### Rate Limiting

| Plan | Requests/min | Concurrent runs | WebSocket connections |
|---|---|---|---|
| Free | 10 | 1 | 1 |
| Pro | 60 | 5 | 5 |
| Team | 200 | 20 | 20 |
| Enterprise | Custom | Custom | Custom |

### Billing Models

```python
class Plan(models.Model):
    name = models.CharField(max_length=50)          # "free", "pro", "team", "enterprise"
    display_name = models.CharField(max_length=100)
    price_monthly_usd = models.DecimalField(max_digits=8, decimal_places=2)
    token_budget = models.BigIntegerField()          # monthly token limit
    max_agents = models.IntegerField()
    max_deep_agents = models.IntegerField()
    max_tools = models.IntegerField()
    max_mcp_connections = models.IntegerField()
    max_memory_stores = models.IntegerField()
    max_facts_per_store = models.IntegerField()
    max_knowledge_docs = models.IntegerField()
    trace_retention_days = models.IntegerField()
    max_iterations_per_run = models.IntegerField()
    parallel_tools_allowed = models.BooleanField()
    deep_agents_allowed = models.BooleanField()
    mcp_export_allowed = models.BooleanField()
    max_team_members = models.IntegerField()
    api_rate_limit_per_min = models.IntegerField()
    max_concurrent_runs = models.IntegerField()
    is_active = models.BooleanField(default=True)

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    status = models.CharField(choices=[
        ("active", "Active"),
        ("past_due", "Past Due"),
        ("cancelled", "Cancelled"),
        ("trialing", "Trialing"),
    ])
    stripe_subscription_id = models.CharField(max_length=100, blank=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)

class UsageAlert(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    threshold = models.IntegerField()        # 75, 90, 95, 100
    alert_type = models.CharField(choices=[
        ("email", "Email"),
        ("banner", "Banner"),
        ("throttle", "Throttle"),
        ("block", "Block"),
    ])
    triggered_at = models.DateTimeField(auto_now_add=True)
    acknowledged = models.BooleanField(default=False)
```

### Overage Options (Pro & Team)

| Option | How it works |
|---|---|
| **Hard stop** (default) | Agent runs blocked at 100%. Wait for monthly reset. |
| **Pay-as-you-go overage** | Continue running at $0.50 per additional 100K tokens. Billed at end of month. |
| **Auto-upgrade** | Automatically upgrade to next plan when budget exceeded. Can set max spend cap. |

Users configure their overage preference in Settings:

```
┌─────────────────────────────────────────────────────────┐
│ Settings > Billing > Overage Policy                      │
│                                                         │
│ When you exceed your monthly token budget:              │
│                                                         │
│ ● Hard stop — block agent runs until reset              │
│ ○ Pay-as-you-go — $0.50 per 100K extra tokens          │
│   Max overage: [$50.00        ] per month               │
│ ○ Auto-upgrade — move to next plan automatically        │
│                                                         │
│ [Save]                                                  │
└─────────────────────────────────────────────────────────┘
```

### Free Plan Restrictions

| Restriction | Detail |
|---|---|
| 100K tokens/month | ~50 simple agent runs or ~10 deep agent runs |
| 3 agents max | Can create up to 3 agent configs |
| 1 deep agent | GoalAgent or ReflectiveAgent only (no Supervisor) |
| 5 tools | 5 custom tools max |
| 1 MCP connection | Connect 1 external MCP server |
| 4 max iterations | Agent runs limited to 4 tool-calling loops |
| No parallel tools | Sequential execution only |
| No MCP export | Cannot export agents as MCP servers |
| 24h trace retention | Traces auto-deleted after 24 hours |
| 10 req/min rate limit | Throttled API access |
| 1 concurrent run | Only 1 agent can run at a time |
| No team members | Solo use only |
| Community support | GitHub issues only |

### Upgrade Flow

```
User hits limit
     │
     ▼
┌────────────────────────────┐
│  Your monthly token budget │
│  has been reached.         │
│                            │
│  ████████████████████ 100% │
│  100K / 100K tokens        │
│                            │
│  Options:                  │
│  ┌──────────────────────┐  │
│  │ Upgrade to Pro — $29 │  │
│  │ 5M tokens/month      │  │
│  │ 25 agents, 10 deep   │  │
│  │ [Upgrade Now]        │  │
│  └──────────────────────┘  │
│                            │
│  Or wait until May 1 for   │
│  your free tokens to reset │
│                            │
│  [View usage details]      │
└────────────────────────────┘
```

---

## AI-Powered Assistants (Power Features)

Two built-in AI assistants that make the platform smarter than any competitor.

### AI Assistant 1: Tool Recommender & Generator

When a user describes what they need, the AI recommends tools from the platform's catalog, generates new tool code, and lets the user test it — all in one flow.

```
┌─────────────────────────────────────────────────────────┐
│ AI Tool Assistant                                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ User: "I need to analyze CSV files and create charts"   │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 🤖 Based on your request, I recommend:             │ │
│ │                                                     │ │
│ │ Existing tools:                                     │ │
│ │ ✅ code_execution — run Python for analysis         │ │
│ │ ✅ workspace_files — read/write CSV files           │ │
│ │                                                     │ │
│ │ New tools I can create for you:                     │ │
│ │ 🔧 csv_analyzer — parse CSV, compute statistics    │ │
│ │ 🔧 chart_generator — create matplotlib charts      │ │
│ │                                                     │ │
│ │ Here's the generated code for csv_analyzer:         │ │
│ │ ┌───────────────────────────────────────────────┐   │ │
│ │ │ def csv_analyzer(path: str, ...) -> str:     │   │ │
│ │ │     import pandas as pd                       │   │ │
│ │ │     df = pd.read_csv(path)                    │   │ │
│ │ │     return df.describe().to_string()           │   │ │
│ │ └───────────────────────────────────────────────┘   │ │
│ │                                                     │ │
│ │ [✏️ Edit Code] [▶️ Test Tool] [💾 Save to My Tools] │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ [Ask another question...]                               │
└─────────────────────────────────────────────────────────┘
```

**How it works:**

```
API: POST /api/ai/recommend-tools/
Body: {"description": "I need to analyze CSV files and create charts"}
Response: {
    "existing_tools": [
        {"name": "code_execution", "reason": "Run Python for data analysis"},
        {"name": "workspace_files", "reason": "Read/write CSV files"}
    ],
    "generated_tools": [
        {
            "name": "csv_analyzer",
            "description": "Parse CSV files and compute statistics",
            "code": "def csv_analyzer(path: str) -> str: ...",
            "schema": {...}
        }
    ]
}
```

**Backend implementation:**
- Uses the user's default provider/model from settings
- Sends the platform's full tool catalog schema as context
- LLM recommends existing tools + generates new tool code
- User can edit, test, and save generated tools
- Test uses the tool's own `run()` method with sample input

### AI Assistant 2: Agent Builder Copilot

When a user wants to create an agent or deep agent, the AI recommends how to set it up — which tools to link, which MCP servers, what prompt, what type of deep agent.

```
┌─────────────────────────────────────────────────────────┐
│ AI Agent Assistant                                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ User: "I want to build a research agent that can        │
│        search the web, analyze data, and write reports" │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 🤖 I recommend this setup:                         │ │
│ │                                                     │ │
│ │ Agent Type: Supervisor (deep agent)                 │ │
│ │ Reason: You need multiple specialized workers       │ │
│ │                                                     │ │
│ │ Workers:                                            │ │
│ │ ├── researcher                                      │ │
│ │ │   Tools: web_search, open_url                     │ │
│ │ │   Prompt: "You research topics thoroughly..."     │ │
│ │ ├── analyst                                         │ │
│ │ │   Tools: code_execution, csv_analyzer             │ │
│ │ │   Prompt: "You analyze data and find trends..."   │ │
│ │ └── writer                                          │ │
│ │     Tools: workspace_files                          │ │
│ │     Prompt: "You write clear reports..."            │ │
│ │                                                     │ │
│ │ MCP Servers: GitHub MCP (for repo data)             │ │
│ │ Memory: Shared research memory (summary strategy)   │ │
│ │ Max delegations: 6                                  │ │
│ │                                                     │ │
│ │ [🚀 Create This Agent] [✏️ Customize] [💬 Refine]  │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ [Ask another question...]                               │
└─────────────────────────────────────────────────────────┘
```

**How it works:**

```
API: POST /api/ai/recommend-agent/
Body: {"description": "research agent that searches web, analyzes data, writes reports"}
Response: {
    "agent_type": "supervisor",
    "reason": "Multiple specialized workers needed for research, analysis, and writing",
    "config": {
        "workers": [
            {"name": "researcher", "tools": ["web_search", "open_url"], "prompt": "..."},
            {"name": "analyst", "tools": ["code_execution"], "prompt": "..."},
            {"name": "writer", "tools": ["workspace_files"], "prompt": "..."}
        ],
        "mcp_servers": ["github"],
        "memory": {"type": "shared", "strategy": "summary"},
        "max_delegations": 6
    },
    "one_click_create": true
}
```

**One-click create:** User clicks "Create This Agent" and the backend:
1. Creates worker agent configs
2. Creates the deep agent config
3. Links tools, MCP, memory
4. Returns the ready-to-run deep agent

### API Endpoints for AI Assistants

```
AI Assistants:
  POST   /api/ai/recommend-tools/      # describe need → get tool recommendations + generated code
  POST   /api/ai/recommend-agent/      # describe goal → get full agent setup recommendation
  POST   /api/ai/create-from-recommendation/  # one-click create from recommendation
```

### Django Models

```python
class AIRecommendation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    recommendation_type = models.CharField(choices=[("tool", "Tool"), ("agent", "Agent")])
    user_description = models.TextField()
    recommendation = models.JSONField()
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## Knowledge Base — File-Based Memory

Users can upload files (PDF, TXT, Markdown, CSV) to create a knowledge base that agents and deep agents can search.

### File Upload & Processing

```
┌─────────────────────────────────────────────────────────┐
│ Knowledge Base: "Product Docs"              [+ Upload]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Files (12)                                              │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 📄 api-reference.md          42 KB    23 chunks     │ │
│ │ 📄 deployment-guide.pdf      1.2 MB   67 chunks     │ │
│ │ 📄 faq.txt                   8 KB     5 chunks      │ │
│ │ 📄 sales-data.csv            256 KB   rows: 1,247   │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Linked to:                                              │
│ ├── 🤖 support-agent (Agent)                           │
│ ├── 🎯 research-bot (GoalAgent)                        │
│ └── 👔 content-team (Supervisor)                       │
│                                                         │
│ Search:                                                 │
│ [How do I deploy?                              ] [🔍]   │
│                                                         │
│ Results:                                                │
│ ├── deployment-guide.pdf (chunk 12): "To deploy..."    │
│ └── api-reference.md (chunk 3): "Deploy endpoint..."   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### File Processing Pipeline

```
User uploads file
     │
     ▼
┌─────────────┐    ┌──────────────┐    ┌────────────────┐
│ Parse file  │───▶│ Chunk text   │───▶│ Store chunks   │
│ (PDF/TXT/   │    │ (500 tokens  │    │ as MemoryFacts │
│  MD/CSV)    │    │  per chunk)  │    │ in MemoryStore │
└─────────────┘    └──────────────┘    └────────────────┘
```

### API Endpoints

```
Knowledge Base:
  POST   /api/memory/{id}/upload/          # upload file (multipart)
  GET    /api/memory/{id}/files/           # list uploaded files
  DELETE /api/memory/{id}/files/{file_id}/ # delete file + its chunks
  POST   /api/memory/{id}/search/          # semantic search across all files
```

### Supported File Types

| Type | Parser | Chunking |
|---|---|---|
| `.md` | Markdown sections (split on `##`) | 500 tokens per chunk |
| `.txt` | Plain text paragraphs | 500 tokens per chunk |
| `.pdf` | PyPDF2 / pdfplumber | Page-based, 500 tokens |
| `.csv` | pandas, first row = headers | Row groups, 50 rows per chunk |

### Django Model

```python
class KnowledgeFile(models.Model):
    memory_store = models.ForeignKey(MemoryStore, related_name="files", on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)  # "md", "txt", "pdf", "csv"
    file_size = models.IntegerField()
    chunk_count = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # Chunks stored as MemoryFact with metadata={"file_id": ..., "chunk_index": ...}
```

### Linking Knowledge Base to Agents

```
Agent Builder:
  ── Memory ────────
  [✓] Product Docs (12 files, 137 chunks)
  [✓] Customer FAQ (3 files, 15 chunks)
  [ ] Sales Data (1 file, 1247 rows)
  [+] Create Knowledge Base
```

When an agent runs, it automatically searches the linked knowledge base before responding.

---

## What Makes This Better Than LangSmith / LangChain Cloud

| Feature | LangSmith | SHIPIT Cloud |
|---|---|---|
| Visual tool builder | No | Yes — create, test, edit tools |
| Visual agent builder | No | Yes — link tools, MCP, memory |
| Deep agent studio | No | Yes — GoalAgent, Supervisor, etc. |
| Real-time streaming | Traces only | Live streaming + traces |
| Agent-to-MCP export | No | Yes — one-click MCP server |
| Knowledge base (file upload) | No | Yes — PDF, TXT, MD, CSV upload + chunking |
| AI Tool Recommender | No | Yes — describe need, get tool code |
| AI Agent Builder Copilot | No | Yes — describe goal, one-click create |
| Self-hostable | No (SaaS only) | Yes — Docker Compose |
| SSO + GitHub login | Yes | Yes |
| Token budget tracking | Yes | Yes — with usage charts + enforcement |
| Plan tiers | Yes | Yes — Free/Pro/Team/Enterprise |
| Open source engine | No | Yes — shipit_agent MIT |

---

## Advanced Features — Inspired by Claude Managed Agents

These features go beyond what any existing platform offers, inspired by Anthropic's managed agents architecture.

### 1. Scheduled Agent Runs (Cron Jobs)

Users schedule agents to run automatically on a recurring basis.

```
API: POST /api/schedules/
Body: {
    "agent_id": 5,           // or deep_agent_id
    "prompt": "Check server health and report issues",
    "cron": "0 */6 * * *",   // every 6 hours
    "enabled": true,
    "notify": ["email", "webhook"]
}

Django Model:
class AgentSchedule(models.Model):
    owner = FK(User)
    agent = FK(AgentConfig, null=True)
    deep_agent = FK(DeepAgent, null=True)
    prompt = TextField()
    cron_expression = CharField(max_length=100)
    is_enabled = BooleanField(default=True)
    last_run_at = DateTimeField(null=True)
    next_run_at = DateTimeField(null=True)
    notify_channels = JSONField(default=list)  # ["email", "webhook", "slack"]
    created_at = DateTimeField(auto_now_add=True)
```

Backend: Use `django-celery-beat` for cron scheduling. Each scheduled run creates a Trace.

### 2. Webhook Triggers

External services trigger agent runs via HTTP webhook.

```
API: POST /api/webhooks/
Body: {
    "name": "github-pr-review",
    "agent_id": 5,
    "prompt_template": "Review this PR: {payload.pull_request.html_url}",
    "secret": "auto-generated",
    "enabled": true
}

Trigger: POST /api/webhooks/{webhook_id}/trigger/
Body: { any JSON payload }
→ Agent runs with the rendered prompt template

Django Model:
class Webhook(models.Model):
    owner = FK(User)
    name = CharField(max_length=100)
    agent = FK(AgentConfig, null=True)
    deep_agent = FK(DeepAgent, null=True)
    prompt_template = TextField()  # supports {payload.key} references
    secret = CharField(max_length=64)
    is_enabled = BooleanField(default=True)
    trigger_count = IntegerField(default=0)
    last_triggered_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)
```

### 3. Session Persistence — Agents Resume Across Runs

Agents maintain conversation state across multiple runs within a session.

```
API: POST /api/sessions/
Body: {"agent_id": 5, "name": "research-session"}

API: POST /api/sessions/{session_id}/send/
Body: {"prompt": "Now compare those frameworks"}
→ Agent sees full conversation history from previous messages in this session

Django Model:
class AgentSession(models.Model):
    owner = FK(User)
    agent = FK(AgentConfig, null=True)
    deep_agent = FK(DeepAgent, null=True)
    name = CharField(max_length=200)
    messages = JSONField(default=list)  # full conversation history
    memory_store = FK(MemoryStore, null=True)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

UI: Chat-like interface where users send multiple messages to the same agent session.

### 4. Agent Handoffs

One agent delegates to another mid-run with structured context. Like Claude's managed agent handoffs.

```
shipit_agent lib addition:

class HandoffTool(Tool):
    """Tool that allows an agent to hand off to another agent."""
    name = "handoff"
    description = "Hand off the task to a specialized agent"

    def run(self, context, target_agent: str, message: str, **kwargs):
        # Find target agent, run it, return result
        ...

Usage in deep agents:
supervisor = Supervisor(
    llm=llm,
    workers=[...],
    allow_handoffs=True,  # workers can hand off to each other
)
```

### 5. Context Window Visualization

Show users exactly how much of the context window is used, what's in it, and when compaction happens.

```
UI Component: ContextWindowBar
┌─────────────────────────────────────────────────────────┐
│ Context Window: 47,231 / 128,000 tokens (37%)           │
│ ████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│                                                         │
│ Breakdown:                                              │
│ ├── System prompt:    2,100 tokens  ██                  │
│ ├── Conversation:     8,400 tokens  ████                │
│ ├── Tool schemas:     6,200 tokens  ███                 │
│ ├── Tool results:    22,100 tokens  ███████████         │
│ └── Memory context:   8,431 tokens  ████                │
│                                                         │
│ ⚠ Compaction will trigger at 96,000 tokens (75%)       │
└─────────────────────────────────────────────────────────┘
```

### 6. Agent Versioning

Track changes to agent configs over time. Roll back to previous versions.

```
Django Model:
class AgentVersion(models.Model):
    agent = FK(AgentConfig)
    version = IntegerField()
    config_snapshot = JSONField()  # full config at this version
    change_summary = TextField()
    created_by = FK(User)
    created_at = DateTimeField(auto_now_add=True)
```

### 7. Agent Templates / Marketplace

Pre-built agent templates users can clone and customize.

```
Django Model:
class AgentTemplate(models.Model):
    name = CharField(max_length=200)
    description = TextField()
    category = CharField()  # "research", "support", "content", "data"
    agent_type = CharField()  # "agent", "goal", "supervisor", etc.
    config = JSONField()
    author = FK(User, null=True)
    is_public = BooleanField(default=True)
    clone_count = IntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True)
```

### 8. Real-Time Collaboration

Multiple team members can watch the same agent run in real time via shared WebSocket.

### 9. Agent Metrics Dashboard

Track agent performance over time: success rate, avg response time, token efficiency, tool usage patterns.

```
┌─────────────────────────────────────────────────────────┐
│ Agent: research-bot          Last 30 days               │
│                                                         │
│ Success Rate:  94%  ████████████████████░░              │
│ Avg Response:  4.2s                                     │
│ Avg Tokens:    1,847/run                                │
│ Total Runs:    234                                      │
│                                                         │
│ Tool Usage:                                             │
│ web_search     ████████████████ 67%                     │
│ code_exec      ████████ 31%                             │
│ open_url       ██ 8%                                    │
│                                                         │
│ Daily Runs:                                             │
│ ▄▆█▇▅▆██▇▅▄▆▇█▅▆▇█▆▅▄▃▅▆▇█▆▅▄▃                       │
└─────────────────────────────────────────────────────────┘
```

### Updated Comparison

| Feature | Claude Managed Agents | LangSmith | SHIPIT Cloud |
|---|---|---|---|
| Scheduled runs | Yes | No | Yes |
| Webhook triggers | Yes | No | Yes |
| Session persistence | Yes | No | Yes |
| Agent handoffs | Yes | No | Yes |
| Context visualization | No | No | Yes |
| Agent versioning | No | No | Yes |
| Template marketplace | No | No | Yes |
| Real-time collaboration | No | No | Yes |
| Agent metrics | No | Yes (traces) | Yes (dedicated dashboard) |
| Visual agent builder | No | No | Yes |
| Deep agents (Goal, Reflective) | No | No | Yes |
| AI Tool Recommender | No | No | Yes |
| Self-hostable | No | No | Yes |
| Open source engine | No | No | Yes |

---

## Implementation Status — What's Done vs What's Left

### DONE (Built in this session)

| Category | Feature | Status |
|---|---|---|
| **Backend Auth** | JWT access + refresh tokens | Done |
| **Backend Auth** | Google OAuth (verify token, create user) | Done |
| **Backend Auth** | GitHub OAuth (exchange code, create user) | Done |
| **Backend Auth** | 2FA TOTP setup, verify, enable, disable, status | Done |
| **Backend Auth** | Token refresh endpoint | Done |
| **Backend Auth** | User data isolation (all queries filter by owner) | Done |
| **Backend Auth** | Production auth enforcement (no demo fallback) | Done |
| **Backend DB** | PostgreSQL config with SQLite fallback | Done |
| **Backend API** | DELETE for deep agents | Done |
| **Backend API** | AI Tool Recommender (`/api/ai/recommend-tools/`) | Done |
| **Backend API** | AI Agent Copilot (`/api/ai/recommend-agent/`) | Done |
| **Backend API** | One-click create from recommendation | Done |
| **Backend API** | File upload + chunking (`/api/memory/{id}/upload/`) | Done |
| **Backend API** | File listing (`/api/memory/{id}/files/`) | Done |
| **Backend Infra** | Dockerfile (Python 3.11 + gunicorn) | Done |
| **Frontend UI** | 16 reusable components (Button, Input, Select, SearchSelect, MultiSelect, Checkbox, Toggle, Card, Badge, Modal, ConfirmDialog, Tabs, Toast, Spinner, Textarea) | Done |
| **Frontend Auth** | JWT API client with auto-refresh on 401 | Done |
| **Frontend Auth** | Login page (Google GIS SDK, GitHub redirect, email/password, 2FA) | Done |
| **Frontend Auth** | Register page with validation | Done |
| **Frontend Auth** | GitHub OAuth callback page | Done |
| **Frontend CRUD** | All missing API calls (delete/update for tools, agents, deep agents, MCP, memory) | Done |
| **Frontend Pages** | Tool detail — editable form + delete | Done |
| **Frontend Pages** | Agent detail — editable form + provider/model select + delete | Done |
| **Frontend Pages** | Deep agent detail — editable form + type selector + delete | Done |
| **Frontend Pages** | MCP Connect page | Done |
| **Frontend Pages** | Knowledge Base page (facts + search + upload tabs) | Done |
| **Frontend Pages** | Providers settings page | Done |
| **Frontend Pages** | API Keys page (create, list, revoke) | Done |
| **Frontend Pages** | Billing page (plan cards, upgrade, usage) | Done |
| **Frontend Pages** | AI Assistant page (tool recommender + agent copilot) | Done |
| **Frontend Nav** | Sidebar with grouped sections, icons, collapse, logout | Done |
| **Frontend Routes** | 27 routes — all spec pages covered | Done |
| **Infra** | Docker Compose (PostgreSQL + Redis + Backend + Frontend) | Done |
| **Infra** | Frontend Dockerfile (Node build + nginx) | Done |
| **Infra** | Nginx config (SPA routing + API proxy) | Done |
| **Infra** | .env.example for backend + frontend | Done |
| **Infra** | .gitignore | Done |

### LEFT TO BUILD (Next sessions)

| Priority | Feature | Backend | Frontend | Agent Lib |
|---|---|---|---|---|
| **P0** | Scheduled agent runs (cron) | `AgentSchedule` model + celery-beat + API | Schedule list/create page | — |
| **P0** | Webhook triggers | `Webhook` model + trigger endpoint + secret | Webhook manager page | — |
| **P0** | Session persistence | `AgentSession` model + send endpoint | Chat-like multi-turn UI | — |
| **P1** | Agent handoffs | API to support handoff tracking | Handoff visualization | `HandoffTool` in shipit_agent |
| **P1** | Context window visualization | Token counting in run response | `ContextWindowBar` component | Already has `usage` tracking |
| **P1** | Agent versioning | `AgentVersion` model + diff | Version history sidebar | — |
| **P2** | Template marketplace | `AgentTemplate` model + clone | Template gallery + search | — |
| **P2** | Agent metrics dashboard | Aggregation queries on traces | Charts (daily runs, success rate, tool usage) | — |
| **P2** | Real-time collaboration | WebSocket room per agent run | Shared streaming view | — |
| **P2** | Real MCP server connection | Actually connect to MCP servers via transport | Test connection button, live tool discovery | — |
| **P3** | Stripe billing integration | Stripe checkout + webhook | Payment flow | — |
| **P3** | Email notifications | SendGrid/Mailgun integration | Notification preferences | — |
| **P3** | SAML SSO (Enterprise) | django-allauth SAML | Enterprise SSO config page | — |
| **P3** | Audit log | `AuditEvent` model for config changes | Audit log viewer | — |

### Quick Start for Next Session

```
Work on shipit_ui at /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_ui/
and shipit_agent at /Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/

Design spec: shipit_agent/docs/superpowers/specs/2026-04-10-shipit-cloud-platform-design.md

Build P0 features first:
1. Scheduled agent runs — django-celery-beat + AgentSchedule model + API + frontend page
2. Webhook triggers — Webhook model + /api/webhooks/{id}/trigger/ + frontend manager
3. Session persistence — AgentSession model + /api/sessions/{id}/send/ + chat UI

Then P1:
4. Agent handoffs — HandoffTool in shipit_agent lib + wire in backend + frontend viz
5. Context window visualization — ContextWindowBar frontend component
6. Agent versioning — AgentVersion model + frontend history

Then P2:
7. Template marketplace
8. Agent metrics dashboard
9. Real MCP connection

All data must be user-scoped (owner=user on every model).
Use the UI components in frontend/src/components/ui/.
Make it powerful, clean, sharp.
```
