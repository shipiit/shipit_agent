---
name: API Design
description: Design or review an HTTP or library API for clarity, evolvability and honest failure. Use when adding an endpoint, designing an interface, or reviewing one.
tools: [read_file, grep, glob]
trigger_phrases: ["design an api", "api review", "design this endpoint", "review this interface"]
version: 1.0.0
---

# API Design

An API is a promise about the future. Almost every design decision is really a
question about what will be hard to change later, and the ones that hurt are
rarely the ones that felt hard at the time.

## Name things after what they mean to the caller

The caller does not know your table names or your internal states. An endpoint
called `/api/v1/user_profile_aggregate_view` leaks a schema decision into a
contract you cannot change without a version bump. `/users/{id}/profile` says the
same thing and survives the schema being rewritten.

Same for parameters. `include_deleted` is honest; `mode=2` is a note to yourself.

## Make illegal states unrepresentable

Every optional field is a combination someone will send. Three optional booleans
are eight cases, and you will handle four of them.

Prefer one required field with an enum over several optional booleans. Prefer
separate endpoints over one endpoint with a `type` parameter that changes which
other fields are required — the second shape cannot be validated or typed.

## Errors are part of the interface

An API that returns 500 for a validation failure is an API whose callers cannot
distinguish "I sent something wrong" from "you are broken", so they retry the
first and give up on the second — exactly backwards.

Every error needs three things: a status code with the right *class* (4xx the
caller's fault, 5xx yours), a stable machine-readable code, and a message that
says what to do. `{"error": "invalid_date_range", "message": "start must be
before end"}` is actionable. `{"error": "Bad Request"}` is not.

## Design for the second version now

Three cheap decisions that avoid a breaking change later:

- **Return an object, not an array.** `{"items": [...]}` can grow a
  `next_cursor`; a bare array cannot.
- **Paginate from the start.** Any list that can grow will. Retrofitting
  pagination is a breaking change; shipping it unused is one field.
- **Accept unknown fields, ignore them.** A client sending a field from a newer
  version should not get a 400.

## Idempotency where it costs something

Any operation with a side effect will be retried — by a client, a proxy, a queue,
a person double-clicking. `PUT` and `DELETE` should be naturally idempotent.
`POST` that charges money or sends mail needs an idempotency key, and the answer
"we will handle duplicates later" means duplicates in production.

## Say no to the convenience parameter

The request to add `?expand=orders,items,customer` always arrives. It turns one
endpoint into a query language, makes response size unbounded, and makes caching
impossible. Two round trips are usually fine. If they genuinely are not, that is
a distinct endpoint with a documented shape.

## Reviewing an existing API

Ask, in order: What breaks if a field is added? What does a caller do with each
error? Which combination of optional fields is untested? What is the largest
possible response? Which operation is not safe to retry?

See `references/versioning.md` when the change is not backwards compatible.
