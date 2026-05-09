from __future__ import annotations

ZENDESK_PROMPT = """

## zendesk
Search, read, and comment on Zendesk support tickets and users on a connected
Zendesk instance (https://{subdomain}.zendesk.com). List and preview macros.

**When to use:**
- The user mentions Zendesk tickets, support requests, or customer conversations
- Triaging a queue of tickets by status, priority, or tag
- Adding internal or public comments to a ticket as part of a support workflow
- Previewing what a macro would do to a ticket before applying it manually

**Decision tree:**
- Looking things up?
  - Tickets matching a Zendesk query → `search_tickets` (e.g. `type:ticket status:open priority:high`)
  - A single ticket → `get_ticket` with `id`
  - All recent tickets → `list_tickets` (pass `per_page`, `page`)
  - Users matching a query → `search_users`; a single user → `get_user`
  - Available personal macros → `list_macros`
  - What a macro would do to a ticket (read-only) → `apply_macro`
- Taking action?
  - Add a comment (public or internal note) → `add_comment`
  - File / update / close a ticket → `create_ticket`, `update_ticket`, `close_ticket`
    (these require `allow_writes=True` on the tool — support data is sensitive)

**Rules:**
- Never ask the user for an API token in chat — use the configured credential record
- For destructive writes (create_ticket, update_ticket, close_ticket) confirm intent
  with `request_human_review` first if not explicitly authorized in the prompt
- On rate limit (429) the tool returns `retry_after_seconds`; back off rather than
  retrying in a tight loop
- `apply_macro` is a PREVIEW — it returns what the ticket would look like but does
  NOT persist changes. To actually apply, follow up with `update_ticket`.
- Always include the subdomain in the credential record's `base_url` metadata —
  fail fast rather than guessing
""".strip()
