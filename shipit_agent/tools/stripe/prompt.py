from __future__ import annotations

STRIPE_PROMPT = """

## stripe
Read-heavy Stripe connector for customers, charges, subscriptions, invoices, and
products on a connected Stripe account (api.stripe.com). Writes are gated behind
`allow_writes=True` at tool construction.

**When to use:**
- The user asks about a Stripe customer, charge, subscription, invoice, product,
  or price lookup
- Reconciling billing issues ("why did Alice's card fail?", "what's her plan?")
- Auditing active subscriptions or recent charges before refund / dunning work
- Looking up products and prices in the live or test catalog

**Decision tree:**
- Looking things up?
  - A customer by id → `get_customer`
  - Find a customer by email/name → `search_customers` with a Stripe search DSL
    query like `email:'alice@acme.com'` or `name:'Acme'`
  - Browse customers → `list_customers` (paginate via `starting_after`)
  - Charges on an account → `list_charges` (optionally filter by `customer=cus_...`)
  - One charge → `get_charge`
  - Subscriptions → `list_subscriptions` (filter `customer`, `status`)
  - One subscription → `get_subscription`
  - Invoices → `list_invoices` (filter `customer`, `status`)
  - One invoice → `get_invoice`
  - Catalog → `list_prices`, `list_products` (default `active=true`)
- Taking action? (requires `allow_writes=True`)
  - Create a customer shell → `create_customer` (email, name)
  - Cancel a subscription → `cancel_subscription` (by id)

**Rules:**
- Never ask the user for a secret key in chat — use the configured credential record
- Stripe uses HTTP Basic auth with the secret key as the username (no password).
  The tool handles this automatically.
- Mode (`test` vs `live`) is inferred from the key prefix (`sk_test_…` / `sk_live_…`)
  and surfaced in response metadata — double-check before running a write in live mode
- Writes (`create_customer`, `cancel_subscription`) return `error="writes_disabled"`
  unless the tool was constructed with `allow_writes=True`. For any write, confirm
  intent with `request_human_review` first if not explicitly authorized.
- On rate limit (HTTP 429) the tool returns `error="rate_limited"` with the
  Stripe-provided `retry_after` seconds — back off, do not hot-loop
- Prefer `limit` ≤ 50 for list endpoints; use `starting_after` for cursor pagination
""".strip()
