---
title: Connections
description: Attach Slack, GitHub, Linear, Jira, Notion and 25+ more as tools with one line — per-user OAuth that refreshes itself, from a clean manifest catalog.
---

# Connections

Every integration is an **MCP server**, and every MCP server is one line to
attach. The catalog ships as a clean directory-per-connector — one declarative
`manifest.yaml` each — so the agent reaches Slack, GitHub, Linear, Jira, Notion
and 25+ more as ordinary tools on one toolbelt.

```python
from shipit_agent import Agent, connect, list_connectors

# Browse what ships:
for c in list_connectors():
    print(c.name, "·", c.category, "·", c.description)

# Attach one (hosted, per-user OAuth):
linear = connect("linear", token=user_token)
# …or a local one (stdio, env token):
slack  = connect("slack")

agent = Agent(llm=llm, mcps=[linear, slack])
agent.run("What Linear issues are assigned to me this cycle?")
```

## The catalog

28 connectors across six categories, each its own `manifest.yaml` — adding one
is a data edit, not code:

| Category | Connectors |
| --- | --- |
| **developer** | GitHub · GitLab · Linear · Jira · Confluence · Sentry |
| **communication** | Slack · Discord · Intercom |
| **productivity** | Notion · Asana · ClickUp · Todoist · Google Drive |
| **data** | Postgres · SQLite · Brave Search · Fetch · Google Maps · Airtable |
| **business** | Stripe · PayPal · Square |
| **automation** | Filesystem · Playwright · Puppeteer · Memory · Cloudflare |

Two transports, chosen per connector by its manifest:

- **hosted** — a vendor-run MCP endpoint reached over HTTP/SSE (Linear, Jira,
  Notion, Stripe, Sentry…). No install; the vendor keeps the tools current.
  Most take a **per-user bearer token** — that is where OAuth belongs.
- **stdio** — the official server run locally over `npx`/`uvx` (Slack, Postgres,
  Playwright…). Declares the env vars it needs so a missing one fails up front.

```python
from shipit_agent.connectors import list_connectors, connector_categories

connector_categories()                 # ['automation','business','communication',…]
list_connectors(category="developer")  # just the dev connectors
```

## Only the tools the turn needs

A power user might connect 20 integrations. Twenty MCP servers is easily 150+
tools — and sending every tool's schema on every request would drown the model
and burn tokens on a question that touches none of them. It should not, and it
does not: pass **`deferred_tools=True`** and the agent keeps a small core
resident and lists everything else **by name only** until it reaches for one —
the same progressive disclosure the strongest coding agents use.

```python
agent = Agent(
    llm=llm,
    mcps=[mgr.connect(c, user=user_id) for c in user_connectors],  # all 20
    deferred_tools=True,
)

# A question that needs nothing connected — nothing loads:
agent.run("Summarise the meeting notes I just pasted.")

# A question that needs Linear — the agent tool_searches and loads only Linear:
agent.run("What's assigned to me in Linear this cycle?")
```

Measured on 20 connectors (~160 tools):

| | Tool schema sent to the model |
| --- | --- |
| every tool eager | ~90,000 chars (≈23K tokens) **per request** |
| `deferred_tools=True` | ~1,650 chars — the core set |
| an unrelated turn | **~98% of connector schema never sent** |

So having 20 connectors connected costs almost nothing until a turn actually
uses one. The model sees the names, decides on its own whether any connection is
relevant, and pays only for what it opens.

## Per-user OAuth that refreshes itself

The classic reason connections "work, then stop" is an access token expiring
with nothing to refresh it. `OAuthCredentialManager` fixes that: it resolves the
**right user's** token at call time and **refreshes it transparently** when it's
near expiry.

```python
from shipit_agent.connectors import OAuthCredentialManager, FileTokenStore

mgr = OAuthCredentialManager(FileTokenStore("/var/lib/shipit/tokens"))
mgr.register_preset(
    "linear",
    client_id=LINEAR_CLIENT_ID,
    client_secret=LINEAR_CLIENT_SECRET,
    redirect_uri="https://app.example.com/oauth/linear/callback",
)

# Send the user to connect:
url = mgr.authorize_url(user=user_id, connector="linear")
# …on the callback:
mgr.complete(connector="linear", code=code, state=state)

# Per turn, per user — token resolved + refreshed automatically:
agent = Agent(llm=llm, mcps=[mgr.connect("linear", user=user_id)])
```

The manager also gives you the whole lifecycle:

- **`access_token(user, connector)`** — a valid token, refreshed if stale.
- **`on_unauthorized(user, connector)`** — recover from a live 401 with one refresh.
- **`status(user, connector)`** — `connected` · `expired` · `disconnected`.
- **`connections(user)`** — every connection this user has, with its status, for
  a dashboard and a *reconnect* button.

Refreshes for the same user+connector collapse to one, so a burst of calls after
an expiry never fires a burst of refreshes.

### 38 provider presets

`OAUTH_PRESETS` carries the authorize/token/refresh endpoints for the common
providers — github, slack, notion, linear, atlassian (Jira/Confluence), google,
microsoft, discord, stripe, salesforce, dropbox, box, figma, airtable, monday,
clickup, hubspot and more — so a connector's OAuth is one `register_preset(...)`.

## In your web framework

`FileTokenStore` is only one implementation of the `TokenStore` protocol
(`get / set / delete / connectors_for`). In a web app you back it with your
database, scope every token to the signed-in user, and expose two routes — one
to start the OAuth flow, one for the callback. Below are complete, copyable
setups.

### Django

**1. A model — tokens in the database, not on disk:**

```python
# connectors/models.py
from django.conf import settings
from django.db import models

class ConnectorToken(models.Model):
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    connector = models.CharField(max_length=64, db_index=True)   # "linear", "slack"
    token     = models.JSONField(default=dict)   # access_token, refresh_token, expires_at
    updated   = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = ("user", "connector")
```

**2. Adapters — the `TokenStore` and the OAuth `state` store, both DB/cache-backed:**

```python
# connectors/stores.py
from django.core.cache import cache
from .models import ConnectorToken

class DjangoTokenStore:                       # satisfies TokenStore
    def get(self, user, connector):
        row = ConnectorToken.objects.filter(user_id=user, connector=connector).first()
        return dict(row.token) if row else None
    def set(self, user, connector, token):
        ConnectorToken.objects.update_or_create(
            user_id=user, connector=connector, defaults={"token": token})
    def delete(self, user, connector):
        ConnectorToken.objects.filter(user_id=user, connector=connector).delete()
    def connectors_for(self, user):
        return list(ConnectorToken.objects.filter(user_id=user)
                    .values_list("connector", flat=True))

class DjangoCacheStateStore:                  # satisfies OAuthStateStore (CSRF nonce)
    def save(self, state, payload): cache.set(f"oauth:{state}", payload, 600)
    def load(self, state):          return cache.get(f"oauth:{state}")
    def delete(self, state):        cache.delete(f"oauth:{state}")
```

**3. Build one manager (shared), registering each connector's app credentials:**

```python
# connectors/agent.py
from django.conf import settings
from shipit_agent.connectors import OAuthCredentialManager
from shipit_agent.integrations.oauth import OAUTH_PRESETS
from .stores import DjangoTokenStore, DjangoCacheStateStore

STATE = DjangoCacheStateStore()
manager = OAuthCredentialManager(DjangoTokenStore())

for name, cfg in settings.CONNECTOR_APPS.items():   # {"linear": {"client_id":…}, …}
    helper = OAUTH_PRESETS[cfg["provider"]](
        cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"],
        scopes=cfg["scopes"], state_store=STATE,
    )
    manager.register(name, helper)
```

**4. Views — connect, callback, and use the agent per user:**

```python
# connectors/views.py
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework.response import Response
from shipit_agent import Agent
from shipit_agent.connectors import NotConnected
from .agent import manager

@api_view(["GET"])
def connect(request, name):
    return redirect(manager.authorize_url(user=request.user.id, connector=name))

@api_view(["GET"])
def callback(request, name):
    manager.complete(connector=name, code=request.GET["code"], state=request.GET["state"])
    return redirect("/settings/connections")

@api_view(["GET"])
def connections(request):
    return Response(manager.connections(user=request.user.id))   # {connector: status}

@api_view(["POST"])
def ask(request):
    try:
        server = manager.connect("linear", user=request.user.id)   # token refreshed here
    except NotConnected:
        return Response({"connect": "/connectors/linear/connect"}, status=409)
    agent = Agent(llm=build_llm(), mcps=[server])
    return Response({"answer": agent.run(request.data["prompt"]).output})
```

`manager.connect(...)` resolves and refreshes the signed-in user's token every
call; a user who hasn't connected gets a clean 409 pointing at the connect URL.

### FastAPI

Same manager, different plumbing. Here with an in-memory store (swap for a
SQLAlchemy-backed `TokenStore` in production):

```python
from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from shipit_agent import Agent
from shipit_agent.connectors import OAuthCredentialManager, InMemoryTokenStore, NotConnected
from shipit_agent.integrations.oauth import OAUTH_PRESETS

app = FastAPI()
manager = OAuthCredentialManager(InMemoryTokenStore())
manager.register("linear", OAUTH_PRESETS["linear"](
    CLIENT_ID, CLIENT_SECRET, "https://api.example.com/oauth/linear/callback",
    scopes=["read", "write"]))

@app.get("/connectors/{name}/connect")
def connect(name: str, user=Depends(current_user)):
    return RedirectResponse(manager.authorize_url(user=user.id, connector=name))

@app.get("/oauth/{name}/callback")
def callback(name: str, code: str, state: str):
    manager.complete(connector=name, code=code, state=state)
    return RedirectResponse("/settings/connections")

@app.get("/connections")
def connections(user=Depends(current_user)):
    return manager.connections(user=user.id)

@app.post("/ask")
def ask(prompt: str, user=Depends(current_user)):
    try:
        server = manager.connect("linear", user=user.id)
    except NotConnected:
        return {"connect": "/connectors/linear/connect"}
    return {"answer": Agent(llm=build_llm(), mcps=[server]).run(prompt).output}
```

In both, the manager is created **once** and shared; only the `TokenStore` /
`OAuthStateStore` change per framework. Everything else — refresh, status, 401
recovery — is identical.

## Adding a connector

Drop a directory under `connectors/catalog/` with one `manifest.yaml`:

```yaml
manifest_version: 1
name: linear
description: Linear issues, cycles, projects and comments.
category: developer
icon: "📐"
transport: {type: http, url: https://mcp.linear.app/sse}
auth: {type: oauth, provider: linear, scopes: [read, write]}
suggest: {keywords: [linear, issue, ticket]}
```

That's it — the registry scans the directory, validates the manifest (invalid
ones are skipped with a diagnostic, never a crash), and `connect("linear")`
works. No central list to edit.
