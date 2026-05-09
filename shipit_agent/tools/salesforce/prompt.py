from __future__ import annotations

SALESFORCE_PROMPT = """

## salesforce
Work with Salesforce records (Accounts, Opportunities, Contacts, Tasks) via the REST API
on a connected Salesforce org. Each org has a unique instance URL
(e.g. ``https://acme.my.salesforce.com``) configured on the credential record's
``base_url``.

**When to use:**
- The user mentions Salesforce accounts, opportunities, contacts, or pipeline
- Looking up CRM data ("what's in the pipeline?", "find the Acme contact")
- Running SOQL reports or SOSL full-text search across objects
- Logging an activity / call / email touchpoint on a Salesforce record
- Creating or updating CRM records (gated — see Rules)

**Decision tree:**
- Looking things up?
  - Free-text across objects → `search` with a SOSL query like
    `FIND {acme} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email)`
  - Structured report → `query` with a SOQL string
  - A single record by id → `get_record` with `sobject` + `record_id`
  - Pipeline snapshot → `list_opportunities` (open deals only)
  - Account book → `list_accounts`
  - People → `list_contacts`
- Taking action?
  - Log a call / email / meeting touchpoint → `log_activity` (safe; always allowed)
    - Pass `subject`, `description`, and `related_to_id` (the Account / Opportunity Id)
  - Create or update a record → `create_record` / `update_record`
    - Gated by `allow_writes` on the tool — default is OFF

**Rules:**
- Salesforce data is business-critical. Default to reads; prefer `query` over writes.
- `create_record` and `update_record` require the tool to be constructed with
  `SalesforceTool(allow_writes=True)`. If writes are disabled the tool returns
  `error=writes_disabled` — surface that to the user, do not loop.
- `log_activity` is intentionally always allowed — activity logging is the one
  write path agents may take without explicit confirmation.
- Never ask the user for a token in chat — use the configured credential record.
- If the credential record is missing `base_url` (the org's instance URL) the tool
  returns `error=missing_instance_url`. Instruct the user to set it and stop.
- On 401 the tool returns `error=auth_expired` — the access token must be refreshed
  via OAuth; do not retry blindly.
- On 429 the tool returns `error=rate_limited` with `retry_after_seconds` from the
  Salesforce `Retry-After` header; wait that long or summarize partial results.
- Prefer tight SOQL (`SELECT Id, Name, ... FROM Obj WHERE ... LIMIT N`) — unbounded
  selects will hit the API's response-size cap.
""".strip()
