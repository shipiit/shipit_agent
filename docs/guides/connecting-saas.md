---
title: Connecting SaaS tools — credentials, tokens, setup
description: End-to-end setup for every built-in shipit-agent connector. Where to get each token, what scopes to request, the CredentialRecord shape, and a working example.
---

# Connecting SaaS tools

Every connector in shipit-agent reads its credentials from a shared
`CredentialStore`. You set up credentials **once** — pick your storage
strategy, register each service's record, and every agent that loads the
matching tool picks them up automatically.

> **TL;DR** — build a `CredentialStore`, `put(CredentialRecord(...))` for
> each service, pass the store to your tool constructors via
> `credential_store=...`. That's it.

---

## The shared pattern

Every connector tool follows the same shape:

```text
from shipit_agent import Agent, <ServiceTool>, InMemoryCredentialStore, CredentialRecord

store = InMemoryCredentialStore()
store.set(CredentialRecord(
    key="<service_key>",       # default: the service name
    provider="<service>",
    secrets={...},             # api key, OAuth token, etc.
    metadata={...},            # base_url, instance URL, auth_scheme…
))

tool = <ServiceTool>(credential_store=store)
agent = Agent(llm=llm, tools=[tool])
```

Two storage backends are built in:

- **`InMemoryCredentialStore`** — fast, ephemeral. Good for tests + notebooks.
- **`FileCredentialStore(path=...)`** — JSON on disk. Good for local dev.

For production, subclass `CredentialStore` and back it with AWS Secrets
Manager, GCP Secret Manager, HashiCorp Vault, or your platform of choice
— the interface is six methods.

---

## Quick decision tree

| You have… | Use this |
| --- | --- |
| An OAuth-flow service (Gmail, Drive, Calendar, Sheets, Slack) | See **OAuth helpers** below |
| A service that issues static API tokens (Linear, Notion, HubSpot, GitHub, GitLab, Figma, Stripe, Zendesk) | Create the token in that service's UI, drop it into `secrets["token"]` |
| A Basic-auth / email+token service (Jira, Zendesk) | Email goes in `secrets["email"]`, API token in `secrets["api_token"]` |
| A service with instance URLs (Salesforce, Zendesk, GitHub Enterprise, self-hosted GitLab) | Put the instance URL in `metadata["base_url"]` |

---

# Each connector, end-to-end

One section per service. Click the tool name to jump to its full
reference page.

## Gmail · Drive · Calendar · Sheets (Google Workspace)

All four Google tools share the same OAuth credentials. Google
Workspace admin grants consent via the Google OAuth flow.

**1. Enable APIs** in the [Google Cloud console](https://console.cloud.google.com/):
Gmail API, Google Drive API, Google Calendar API, Google Sheets API.

**2. Create an OAuth 2.0 client** (Application type → Web application)
and note the **client ID + client secret**.

**3. Add scopes** your agents need:

| Scope | For |
| --- | --- |
| `https://www.googleapis.com/auth/gmail.modify` | Gmail read + send + draft |
| `https://www.googleapis.com/auth/drive.readonly` | Drive read |
| `https://www.googleapis.com/auth/calendar` | Calendar read + write |
| `https://www.googleapis.com/auth/spreadsheets` | Sheets read + write |

**4. Run the shipit OAuth helper** to get a user access + refresh token:

```python
from shipit_agent import CredentialRecord, FileCredentialStore, GoogleOAuthHelper, InMemoryOAuthStateStore

store = FileCredentialStore(".shipit_credentials.json")
helper = GoogleOAuthHelper(
    client_id="xxx.apps.googleusercontent.com",
    client_secret="GOCSPX-...",
    redirect_uri="http://localhost:8080/callback",
    scopes=[
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
    state_store=InMemoryOAuthStateStore(),
)

# 1. Send the user to Google.
print(helper.create_authorization_url()["url"])

# 2. Google redirects back with ?code=...&state=...; exchange the code for tokens.
tokens = helper.exchange_code(code="<code from query>", state="<state from query>")

# 3. Save them for the Google tools, with the client id and secret for refreshing.
store.set(CredentialRecord(
    key="gmail",
    provider="gmail",
    secrets={**tokens, "client_id": "xxx.apps.googleusercontent.com", "client_secret": "GOCSPX-..."},
))
```

**5. Use the tools** — they'll read the same credential record:

```python
from shipit_agent import GmailTool, GoogleDriveTool, GoogleCalendarTool, GoogleSheetsTool

agent = Agent(
    llm=llm,
    tools=[GmailTool(), GoogleDriveTool(),
           GoogleCalendarTool(), GoogleSheetsTool()],
    credential_store=store,
)
```

Refresh is automatic — the helper refreshes the access token using the
stored refresh token when it expires.

---

## Slack

**1. Create a Slack app** at <https://api.slack.com/apps>. Pick
"From scratch", name it, attach it to your workspace.

**2. Add Bot Token scopes** under **OAuth & Permissions**:

| Scope | For |
| --- | --- |
| `channels:history` | Read public channel messages |
| `channels:read` | List channels |
| `chat:write` | Post messages |
| `groups:history` | Read private channels (if bot is a member) |
| `search:read` | Search across workspace |
| `users:read` | Look up users |

**3. Install the app to your workspace** — you'll get a
`xoxb-...` **Bot User OAuth Token**.

**4. Register the credential:**

```python
from shipit_agent import CredentialRecord, InMemoryCredentialStore, SlackTool

store = InMemoryCredentialStore()
store.set(CredentialRecord(
    key="slack", provider="slack",
    secrets={"token": "xoxb-..."},
    metadata={"base_url": "https://slack.com/api", "auth_scheme": "Bearer"},
))

slack = SlackTool(credential_store=store)
```

---

## Linear

**1.** Create an API key at <https://linear.app/settings/api>.

**2.** Register:

```python
from shipit_agent import CredentialRecord, LinearTool

store.set(CredentialRecord(
    key="linear", provider="linear",
    secrets={"token": "lin_api_..."},
    metadata={"base_url": "https://api.linear.app/graphql",
              "auth_scheme": "Bearer"},
))
tool = LinearTool(credential_store=store)
```

---

## Jira · Confluence (Atlassian)

Both use the same email + API token pattern.

**1.** Generate an API token at
<https://id.atlassian.com/manage-profile/security/api-tokens>.

**2.** Register (Jira shown; Confluence identical with different `key`
and `base_url`):

```python
from shipit_agent import CredentialRecord, JiraTool, ConfluenceTool

store.set(CredentialRecord(
    key="jira", provider="jira",
    secrets={"email": "you@acme.com", "api_token": "ATATT..."},
    metadata={"base_url": "https://acme.atlassian.net"},
))

store.set(CredentialRecord(
    key="confluence", provider="confluence",
    secrets={"email": "you@acme.com", "api_token": "ATATT..."},
    metadata={"base_url": "https://acme.atlassian.net/wiki"},
))
```

---

## Notion

**1.** Create an internal integration at
<https://www.notion.so/my-integrations> — copy the **Internal Integration Token**.

**2.** In Notion, share each page/database you want the agent to access
with the integration (otherwise it returns 404).

**3.** Register:

```python
store.set(CredentialRecord(
    key="notion", provider="notion",
    secrets={"token": "secret_..."},
    metadata={
        "base_url": "https://api.notion.com",
        "auth_scheme": "Bearer",
        "headers": {"Notion-Version": "2022-06-28"},
    },
))
```

---

## HubSpot

**1.** Create a private app at
<https://app.hubspot.com/private-apps> and grant the scopes your agents
need (`crm.objects.contacts.read`, `.write`, etc.).

**2.** Register:

```python
store.set(CredentialRecord(
    key="hubspot", provider="hubspot",
    secrets={"token": "pat-na1-..."},
    metadata={"base_url": "https://api.hubapi.com",
              "auth_scheme": "Bearer"},
))
```

---

## GitHub *(new in 1.0.7)*

**1.** Create a token at
<https://github.com/settings/personal-access-tokens/new> — prefer a
fine-grained token scoped to the specific repositories.

| Scope / permission | For |
| --- | --- |
| `contents:read` | Read file contents + repo metadata |
| `issues:write` | Create / update / comment on issues |
| `pull_requests:write` | Create / update / review / merge PRs |
| `actions:read` | Read workflow runs |
| `actions:write` | Rerun workflows |

**2.** Register:

```python
from shipit_agent import CredentialRecord, GitHubTool

store.set(CredentialRecord(
    key="github", provider="github",
    secrets={"token": "github_pat_..."},
    # `base_url` optional — defaults to https://api.github.com
    # GitHub Enterprise: metadata={"base_url": "https://ghe.acme.com/api/v3"}
))

github = GitHubTool(credential_store=store)
```

---

## GitLab *(new in 1.0.7)*

**1.** Create a personal access token at
<https://gitlab.com/-/profile/personal_access_tokens>. Scopes: `api`,
`read_api`, `read_repository`, `write_repository`.

**2.** Register:

```python
from shipit_agent import CredentialRecord, GitLabTool

store.set(CredentialRecord(
    key="gitlab", provider="gitlab",
    secrets={"token": "glpat-..."},
    metadata={"base_url": "https://gitlab.com"},
    # Self-hosted: metadata={"base_url": "https://gitlab.acme.com"}
))

gitlab = GitLabTool(credential_store=store)
```

---

## Figma *(new in 1.0.7)*

**1.** Create a PAT at <https://www.figma.com/settings> → **Personal
access tokens**. Grant access to the team(s) and file(s) you want the
agent to reach.

**2.** Register — Figma uses `X-Figma-Token`, not Bearer:

```python
from shipit_agent import CredentialRecord, FigmaTool

store.set(CredentialRecord(
    key="figma", provider="figma",
    secrets={"token": "figd_..."},
    # base_url defaults to https://api.figma.com
))

figma = FigmaTool(credential_store=store)
```

---

## Salesforce *(new in 1.0.7)*

Salesforce requires an OAuth access token **plus your org's instance
URL** (every org has a unique subdomain).

**1.** Create a connected app in **Setup → App Manager → New Connected
App**. Enable "Enable OAuth Settings", pick a callback URL, grant at
minimum `api` and `refresh_token, offline_access` scopes.

**2.** Obtain a bearer token via the OAuth username-password or
authorization-code flow. See Salesforce's
[OAuth 2.0 Web Server Flow](https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_web_server_flow.htm).

**3.** Note your **instance URL** — visible in My Domain settings, e.g.
`https://acme.my.salesforce.com`.

**4.** Register:

```python
from shipit_agent import CredentialRecord, SalesforceTool

store.set(CredentialRecord(
    key="salesforce", provider="salesforce",
    secrets={"access_token": "00D...00!AQE..."},
    metadata={"base_url": "https://acme.my.salesforce.com",
              "auth_scheme": "Bearer"},
))

# Reads + safe activity logging by default.
# Set allow_writes=True to enable create_record / update_record.
sf = SalesforceTool(credential_store=store, allow_writes=False)
```

When the token expires the tool returns `error="auth_expired"` — catch
that in your agent loop and refresh via the `refresh_token` flow.

---

## Stripe *(new in 1.0.7)*

**1.** Get your secret key from <https://dashboard.stripe.com/apikeys>.
Use a **restricted key** (not the full secret key) for production — grant
only `Read` on customers, charges, subscriptions, invoices.

**2.** Register:

```python
from shipit_agent import CredentialRecord, StripeTool

store.set(CredentialRecord(
    key="stripe", provider="stripe",
    secrets={"api_key": "sk_test_..."},     # sk_test_ or sk_live_ or rk_test_
    # base_url defaults to https://api.stripe.com
))

stripe = StripeTool(credential_store=store, allow_writes=False)
```

Stripe uses HTTP Basic auth with the key as username — the tool handles
that for you. `metadata["mode"]` reports "test" or "live" based on the
key prefix.

---

## Google Sheets *(new in 1.0.7)*

See the Google Workspace section above — the same OAuth credentials work
for Sheets. Add the scope
`https://www.googleapis.com/auth/spreadsheets` when you create the OAuth
client.

---

## Zendesk *(new in 1.0.7)*

**1.** Create an API token at **Admin Center → Apps and integrations →
APIs → Zendesk API → Settings → Add API token**.

**2.** Note your **subdomain** — the part before `.zendesk.com` in your
URL.

**3.** Register:

```python
from shipit_agent import CredentialRecord, ZendeskTool

store.set(CredentialRecord(
    key="zendesk", provider="zendesk",
    secrets={"email": "you@acme.com", "api_token": "abc123..."},
    metadata={"base_url": "https://acme.zendesk.com"},
))

zen = ZendeskTool(credential_store=store, allow_writes=False)
```

Zendesk uses Basic auth with `email/token:api_token` — the tool builds
the header. `add_comment` is always enabled (triage), `create_ticket` /
`update_ticket` / `close_ticket` require `allow_writes=True`.

---

## LinkedIn search *(new in 1.0.7)*

**Read-only by design**, no messaging, no automation. LinkedIn's own
Partner API is scarce, so `LinkedInSearchTool` points at third-party
vendors like [Proxycurl](https://nubela.co/proxycurl) or
[RapidAPI](https://rapidapi.com/).

**Proxycurl setup:**

```python
from shipit_agent import CredentialRecord, LinkedInSearchTool

store.set(CredentialRecord(
    key="linkedin", provider="linkedin",
    secrets={"token": "pxl_..."},
    metadata={
        "base_url": "https://nubela.co/proxycurl/api",
        "auth_mode": "bearer",
    },
))

linkedin = LinkedInSearchTool(credential_store=store)
```

**RapidAPI setup** (different auth mode — header-based):

```python
store.set(CredentialRecord(
    key="linkedin", provider="linkedin",
    secrets={"token": "rapid_..."},
    metadata={
        "base_url": "https://linkedin-api.p.rapidapi.com",
        "auth_mode": "api_key_header",
        "api_key_header": "X-RapidAPI-Key",
    },
))
```

The tool's schema deliberately contains **zero** write actions; any
attempt to inject one is blocked by a runtime denylist.

---

## Custom API

If shipit-agent doesn't ship the connector you need, the `CustomAPITool`
points at any HTTP endpoint with whatever auth shape you like. See
[`custom_api`](../tools/connectors.md#custom_api) in the tool reference.

---

# One credential store, all connectors

Real agents use multiple services. Keep everything in one store:

```python
from shipit_agent import (
    Agent, FileCredentialStore, CredentialRecord,
    GmailTool, SlackTool, GitHubTool, SalesforceTool, LinearTool,
)

store = FileCredentialStore(".shipit_credentials.json")

# One-time setup — run these once on a new machine.
for record in [
    CredentialRecord(key="gmail",      provider="gmail",      secrets={"access_token": "...", "refresh_token": "..."},
                     metadata={"base_url": "https://gmail.googleapis.com", "auth_scheme": "Bearer"}),
    CredentialRecord(key="slack",      provider="slack",      secrets={"token": "xoxb-..."},
                     metadata={"base_url": "https://slack.com/api", "auth_scheme": "Bearer"}),
    CredentialRecord(key="github",     provider="github",     secrets={"token": "github_pat_..."}),
    CredentialRecord(key="salesforce", provider="salesforce", secrets={"access_token": "00D..."},
                     metadata={"base_url": "https://acme.my.salesforce.com", "auth_scheme": "Bearer"}),
    CredentialRecord(key="linear",     provider="linear",     secrets={"token": "lin_api_..."},
                     metadata={"base_url": "https://api.linear.app/graphql", "auth_scheme": "Bearer"}),
]:
    store.set(record)

agent = Agent(
    llm=llm,
    tools=[GmailTool(), SlackTool(), GitHubTool(), SalesforceTool(), LinearTool()],
    credential_store=store,
)
```

After the first run, the file `/path/to/.shipit_credentials.json` holds
every token. Subsequent runs skip the registration.

---

# Best practices

### Never hard-code tokens

```python
import os

store.set(CredentialRecord(
    key="github", provider="github",
    secrets={"token": os.environ["GITHUB_TOKEN"]},
))
```

### Rotate regularly

Most providers let you issue multiple tokens with separate names so you
can rotate without downtime. The `CredentialStore.set(record)` call is
idempotent — call it with the new token and every tool picks it up on
the next request.

### Use least-privilege scopes

Agents should never hold write scopes they don't need. Start with
read-only scopes and escalate only when you hit a specific action you
want enabled.

### Gate writes explicitly

Every connector that can mutate business data takes an `allow_writes`
flag. Leave it off by default. Enable per-run when you need it:

```python
# Safe — read-only, even though the token has write scopes.
safe_sf = SalesforceTool(credential_store=store, allow_writes=False)

# Intentional — this run will call create_record / update_record.
writing_sf = SalesforceTool(credential_store=store, allow_writes=True)
```

### Store tokens outside the repo

Never commit `.shipit_credentials.json`. Add it to `.gitignore`:

```
.shipit_credentials.json
*.credentials.json
```

For CI / production, fetch tokens from your secrets manager at startup
and populate an `InMemoryCredentialStore` in-process.

### Observability

Every connector surfaces `error="rate_limited"` with a `retry_after_*`
payload when the provider throttles you. Wire your trace exporter
(`LangSmithExporter` or `OpenTelemetryExporter`) and you'll see rate
events as span attributes — great for capacity planning.

---

## Related

- [Tool catalog](../tools/index.md) — every built-in tool, with
  per-action references.
- [Cost tracking](cost-tracking.md) — per-call cost breakdown across
  LLMs and providers.
- [Observability exports](observability-exports.md) — ship traces to
  LangSmith, Datadog, Grafana, Honeycomb.
- [Notebook 49](https://github.com/shipiit/shipit_agent/blob/main/notebooks/49_sales_lead_enrichment.ipynb)
  — a runnable example using Salesforce + LinkedIn + Gmail.
