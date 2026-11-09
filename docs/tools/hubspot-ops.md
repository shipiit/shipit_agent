---
title: hubspot_ops
description: HubSpot CRM v3 REST wrapper for sales + customer-success agents. One tool, many actions — search / get / create contacts, companies, deals, and notes.
---

# `hubspot_ops`

One tool covering every common HubSpot CRM interaction a sales or CS
agent needs. Auth is a **private-app bearer token** (`HUBSPOT_TOKEN`
env); the tool never logs the token.

> **TL;DR** — `HubspotTool().run(ctx, action="search_contacts", query="acme")`
> hits HubSpot v3 and returns a formatted summary. Switch actions to
> search companies, deals, create contacts, attach notes, etc.

---

## Auth

1. In HubSpot, go to **Settings → Integrations → Private Apps**.
2. Create a private app with scopes:
   `crm.objects.contacts.read/write`,
   `crm.objects.companies.read/write`,
   `crm.objects.deals.read/write`,
   `crm.objects.notes.write`.
3. Export the token:

```bash
export HUBSPOT_TOKEN=pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

4. Instantiate the tool (it reads the env by default):

```python
from shipit_agent.tools.hubspot import HubspotTool

hubspot = HubspotTool()               # or HubspotTool(token="...")
```

---

## Actions

| Action | Required params | Writes? |
| --- | --- | --- |
| `search_contacts` / `search_companies` / `search_deals` | `query` (optional `limit`) | No |
| `get_contact` / `get_company` / `get_deal` | `object_id` | No |
| `create_contact` / `create_deal` | `properties` (dict) | Yes |
| `add_note` | `note`, `object_id`, `object_type` (`contact` \| `company` \| `deal`) | Yes |
| `list_owners` | — | No |

Write actions are flagged `destructive` so the harness's HITL layer
can gate them in interactive runs.

---

## Read examples

```python
from shipit_agent.tools.base import ToolContext
ctx = ToolContext(prompt="demo")

# Search by free-text query
out = hubspot.run(ctx, action="search_contacts", query="acme", limit=10)
print(out.text)
# contact 101 — alice@acme.com — Alice Chen
# contact 203 — bob@acme.com — Bob Ortiz
# ...

# Get one object by id
out = hubspot.run(ctx, action="get_contact", object_id="101")
print(out.text)                                   # full JSON
```

---

## Write examples

```python
# Create a contact
hubspot.run(ctx, action="create_contact", properties={
    "email": "jay@example.com",
    "firstname": "Jay",
    "lastname": "Patel",
    "company": "Example Corp",
    "jobtitle": "VP Engineering",
})

# Create a deal
hubspot.run(ctx, action="create_deal", properties={
    "dealname": "Example Corp — Q3 pilot",
    "amount": "12000",
    "dealstage": "appointmentscheduled",
})

# Attach a note to a deal
hubspot.run(ctx, action="add_note",
    note="Discovery call went well — Jay will loop in infosec next week.",
    object_id="51234",
    object_type="deal",
)
```

---

## Using it with a specialist

The `sales-outreach` specialist pairs naturally with `hubspot_ops`:

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.tools.hubspot import HubspotTool

sales_def = AgentRegistry.default().get("sales-outreach")
sales = Agent(
    llm=llm,
    prompt=sales_def.prompt,
    tools=[HubspotTool()],
    max_iterations=12,
    name=sales_def.name,
)
sales.run("Pull every contact at Acme Corp, pick the VP Eng, draft an outreach referencing their recent Series B.")
```

Same pattern for `customer-success` — hand it `HubspotTool()` so it
can log notes and update lifecycle stages directly.

---

## Error handling

| Scenario | Tool returns |
| --- | --- |
| `HUBSPOT_TOKEN` missing | `Error: HUBSPOT_TOKEN not set…` |
| Unknown action | `Error: unknown action 'xxx'.` |
| Missing required param | `Error: properties object is required.` |
| 4xx/5xx from HubSpot | `Error: HubSpot 429: …rate limit…` (first 300 chars of body) |
| Network error | `Error: Network error: <message>` |

All error paths return `metadata["ok"] = False` so upstream agents can
branch cleanly.

---

## Rate limiting

HubSpot's v3 API has burst limits — the tool does **not** auto-retry.
If you're iterating over thousands of contacts, either:

- Use `autopilot.fanout(items=contact_ids, max_parallel=5, child_budget_frac=0.1)` so
  each child handles its own subset, or
- Wrap the tool in a custom retry layer with exponential backoff.

---

## Notebook

- `notebooks/42_power_tools_computer_use_hubspot_research.ipynb` — including a live-token demo.
- `notebooks/41_specialists_design_pm_sales_cs_marketing.ipynb` — sales-outreach + hubspot_ops together.
