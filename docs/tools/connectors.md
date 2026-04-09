---
title: Connectors
description: Third-party SaaS integrations — Gmail, Drive, Calendar, Slack, Linear, Jira, Notion, Confluence, and a generic Custom API tool.
---

# Connectors

Third-party SaaS integrations. Each connector uses the shared **`CredentialStore`** for OAuth tokens or API keys, so you set up credentials once and every connector picks them up.

| Tool | Tool ID | Service |
|---|---|---|
| `GmailTool` | `gmail_search` | Gmail |
| `GoogleDriveTool` | `google_drive` | Google Drive |
| `GoogleCalendarTool` | `google_calendar` | Google Calendar |
| `SlackTool` | `slack` | Slack |
| `LinearTool` | `linear` | Linear |
| `JiraTool` | `jira` | Atlassian Jira |
| `NotionTool` | `notion` | Notion |
| `ConfluenceTool` | `confluence` | Atlassian Confluence |
| `CustomAPITool` | `custom_api` | Any HTTP API |

---

## Credential setup

All connectors share the same `CredentialStore` interface. You set up credentials once per service, then any agent that loads the corresponding tool automatically uses them.

### File-backed credential store (recommended for local dev)

```python
from shipit_agent import Agent, FileCredentialStore, GmailTool, SlackTool
from shipit_agent.llms import OpenAIChatLLM

credentials = FileCredentialStore(path=".shipit_credentials.json")

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[GmailTool(), SlackTool()],
    credential_store=credentials,
)
```

### In-memory credential store (for tests)

```python
from shipit_agent import InMemoryCredentialStore, CredentialRecord

store = InMemoryCredentialStore()
store.put(CredentialRecord(
    name="gmail",
    type="oauth2",
    token="ya29....",
    refresh_token="1//...",
    metadata={"client_id": "...", "client_secret": "..."},
))
```

### OAuth helpers

For services that need OAuth flows (Google, Slack), shipit-agent ships helpers:

```python
from shipit_agent import GoogleOAuthHelper, OAuthClientConfig

helper = GoogleOAuthHelper(
    config=OAuthClientConfig(
        client_id="...",
        client_secret="...",
        redirect_uri="http://localhost:8080/callback",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    ),
    credential_store=credentials,
    state_store=InMemoryOAuthStateStore(),
)

# Generate authorization URL
auth_url = helper.build_authorization_url()
print(f"Visit: {auth_url}")

# After user authorizes and you receive the callback:
helper.exchange_code(code="...", state="...")
# Token is now in credentials, ready for GmailTool to use
```

See [`notebooks/06_agent_connectors_gmail_and_others.ipynb`](https://github.com/shipiit/shipit_agent/blob/main/notebooks/06_agent_connectors_gmail_and_others.ipynb) for a complete OAuth walk-through.

---

## `gmail_search`

**Class:** `GmailTool`
**Module:** `shipit_agent.tools.gmail`
**Tool ID:** `gmail_search`
**Credential key:** `gmail`

Search, read, draft, and send Gmail messages from a configured Google account.

### Required scopes

```
https://www.googleapis.com/auth/gmail.readonly       # search + read
https://www.googleapis.com/auth/gmail.send           # send + draft
https://www.googleapis.com/auth/gmail.compose        # compose drafts
```

### Schema

```json
{
  "name": "gmail_search",
  "parameters": {
    "type": "object",
    "properties": {
      "action": { "type": "string", "enum": ["search", "read", "send", "draft"] },
      "query":  { "type": "string", "description": "Gmail search query (uses Gmail search syntax)" },
      "message_id": { "type": "string", "description": "Required for read/reply" },
      "to":      { "type": "string" },
      "subject": { "type": "string" },
      "body":    { "type": "string" }
    },
    "required": ["action"]
  }
}
```

### Example

```python
agent.run(
    "Find any emails from acme@example.com in the last week and summarize them."
)
# Agent calls:
#   1. gmail_search action=search query="from:acme@example.com newer_than:7d"
#   2. gmail_search action=read message_id=<id>  for each result
#   3. Returns a summary
```

---

## `google_drive`

**Class:** `GoogleDriveTool`
**Module:** `shipit_agent.tools.google_drive`
**Tool ID:** `google_drive`
**Credential key:** `google_drive`

Search and list Google Drive files. (Read content of Docs/Sheets requires the appropriate scopes.)

### Required scopes

```
https://www.googleapis.com/auth/drive.metadata.readonly   # search/list
https://www.googleapis.com/auth/drive.readonly            # read content
```

### Schema

```json
{
  "name": "google_drive",
  "parameters": {
    "type": "object",
    "properties": {
      "action": { "type": "string", "enum": ["search", "list", "get"] },
      "query":  { "type": "string", "description": "Drive search query" },
      "file_id": { "type": "string" }
    },
    "required": ["action"]
  }
}
```

---

## `google_calendar`

**Class:** `GoogleCalendarTool`
**Module:** `shipit_agent.tools.google_calendar`
**Tool ID:** `google_calendar`
**Credential key:** `google_calendar`

Search and list calendar events.

### Required scopes

```
https://www.googleapis.com/auth/calendar.readonly         # read events
https://www.googleapis.com/auth/calendar.events           # create/update events
```

### Example

```python
agent.run("What meetings do I have tomorrow?")
# Agent calls google_calendar action=search query="tomorrow"
```

---

## `slack`

**Class:** `SlackTool`
**Module:** `shipit_agent.tools.slack`
**Tool ID:** `slack`
**Credential key:** `slack`

Search Slack messages and post Slack messages. Uses a bot token (`xoxb-...`) typed at workspace install.

### Required Slack OAuth scopes

```
channels:read
channels:history
chat:write
search:read
```

### Schema

```json
{
  "name": "slack",
  "parameters": {
    "type": "object",
    "properties": {
      "action":  { "type": "string", "enum": ["search", "post"] },
      "query":   { "type": "string", "description": "Slack search query" },
      "channel": { "type": "string", "description": "Channel ID or name (e.g. #general)" },
      "text":    { "type": "string", "description": "Message body to post" }
    },
    "required": ["action"]
  }
}
```

### Example

```python
agent.run("Post 'deployment finished ✅' to #releases")
```

---

## `linear`

**Class:** `LinearTool`
**Module:** `shipit_agent.tools.linear`
**Tool ID:** `linear`
**Credential key:** `linear`

Search Linear issues and create new ones via Linear's GraphQL API.

### Authentication

Linear uses **personal API keys** — generate at https://linear.app/settings/api. Store as `linear` credential key.

### Schema

```json
{
  "name": "linear",
  "parameters": {
    "type": "object",
    "properties": {
      "action":      { "type": "string", "enum": ["search", "create"] },
      "query":       { "type": "string", "description": "Search query (matches title + description)" },
      "team_id":     { "type": "string", "description": "Linear team ID (required for create)" },
      "title":       { "type": "string" },
      "description": { "type": "string" },
      "priority":    { "type": "integer", "description": "0=none, 1=urgent, 2=high, 3=normal, 4=low" },
      "assignee_id": { "type": "string" }
    },
    "required": ["action"]
  }
}
```

### Example

```python
agent.run(
    "Create a Linear issue in team ENG titled 'Investigate flaky test in CI' "
    "with priority high."
)
```

---

## `jira`

**Class:** `JiraTool`
**Module:** `shipit_agent.tools.jira`
**Tool ID:** `jira`
**Credential key:** `jira`

Search Jira issues and create new ones via the Jira REST API. Works with both Jira Cloud and Jira Server.

### Authentication

Jira Cloud uses **API tokens** — generate at https://id.atlassian.com/manage-profile/security/api-tokens. Store as `jira` credential with `metadata={"email": "you@company.com", "domain": "yourorg.atlassian.net"}`.

### Example

```python
agent.run(
    "Search Jira for any open bugs assigned to me in project PROJ."
)
```

---

## `notion`

**Class:** `NotionTool`
**Module:** `shipit_agent.tools.notion`
**Tool ID:** `notion`
**Credential key:** `notion`

Search Notion pages and create new ones via the Notion API.

### Authentication

Notion uses **integration tokens** — create at https://www.notion.so/my-integrations and share specific pages with the integration. Store as `notion` credential.

### Example

```python
agent.run(
    "Find the Notion page about our deployment runbook."
)
```

---

## `confluence`

**Class:** `ConfluenceTool`
**Module:** `shipit_agent.tools.confluence`
**Tool ID:** `confluence`
**Credential key:** `confluence`

Search and create Confluence pages via the Confluence Cloud REST API.

### Authentication

Same as Jira — API token + email + domain. Stored as `confluence` credential.

---

## `custom_api`

**Class:** `CustomAPITool`
**Module:** `shipit_agent.tools.custom_api`
**Tool ID:** `custom_api`
**Credential key:** `custom_api`

Call **any configured HTTP API** with custom auth. Use this when there's no built-in connector for your service.

### When to use

- Internal company APIs (your own backend, internal microservices)
- Third-party services without a dedicated shipit connector
- Webhooks and miscellaneous HTTP endpoints
- Quick prototyping before deciding whether to write a dedicated tool

### Schema

```json
{
  "name": "custom_api",
  "parameters": {
    "type": "object",
    "properties": {
      "method":  { "type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"] },
      "path":    { "type": "string", "description": "Path appended to the base URL" },
      "body":    { "type": "object", "description": "Request body (for POST/PUT/PATCH)" },
      "params":  { "type": "object", "description": "Query string parameters" },
      "headers": { "type": "object", "description": "Additional request headers" }
    },
    "required": ["method", "path"]
  }
}
```

### Configuration

The credential record holds the base URL, auth type, and auth value:

```python
from shipit_agent import CredentialRecord, FileCredentialStore

store = FileCredentialStore(path=".shipit_credentials.json")
store.put(CredentialRecord(
    name="custom_api",
    type="bearer",
    token="my-secret-token",
    metadata={
        "base_url": "https://api.mycompany.internal",
        "default_headers": {"X-Client": "shipit-agent"},
    },
))
```

Supported auth types: `bearer`, `basic`, `api_key`, `none`.

### Example

```python
agent.run(
    "Call POST /v1/orders with body {customer: 'alice', items: [...]} on the internal API."
)
```

---

## Building your own connector

The connector pattern is simple — subclass `BaseConnectorTool` and implement `run()`. See `shipit_agent/tools/connector_base.py` for the base class and `shipit_agent/tools/linear/linear_tool.py` for a worked example.

```python
from shipit_agent.tools.connector_base import BaseConnectorTool
from shipit_agent.tools.base import ToolContext, ToolOutput

class MyServiceTool(BaseConnectorTool):
    name = "my_service"
    description = "Search and update records in MyService."

    def __init__(self, *, credential_key="my_service", credential_store=None):
        super().__init__(credential_key=credential_key, credential_store=credential_store)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {...},
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        credential = self._get_credential(context)
        # Use credential.token to call the API
        ...
        return ToolOutput(text="...", metadata={...})
```

Once registered, your connector behaves identically to the built-in ones — same credential store, same event lifecycle, indexed by `tool_search`, paired correctly for Bedrock.

---

## Security notes

- **Credentials never appear in events, traces, or memory facts.** Only the connector's outputs are surfaced
- **Each connector validates its credential** before making network calls — missing or expired tokens fail fast with a clear error
- **Outbound requests** are made through stdlib `urllib` (no third-party HTTP library) — limits the attack surface
- For OAuth flows, use the included `GoogleOAuthHelper` and `SlackOAuthHelper` rather than rolling your own — they handle PKCE, state validation, and token refresh

---

## Next: [Custom tools guide →](../guides/custom-tools.md)
