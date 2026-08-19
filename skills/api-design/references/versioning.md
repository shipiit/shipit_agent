# When a change is not backwards compatible

## Is it actually breaking?

Not breaking: adding an endpoint; adding an optional request field; adding a
response field; adding an enum value a client can ignore; relaxing a validation.

Breaking: removing or renaming anything; making an optional field required;
changing a type — including integer to string id; narrowing validation; changing
a status code; changing default behaviour; adding an enum value a client must
handle.

The middle case catches people out: **adding an enum value is breaking for any
client that switches exhaustively on it.** If clients must handle every value,
adding one is a version bump.

## Ways to version, and what each costs

**URL path** (`/v2/users`) — visible, easy to route, easy to cache. Cost:
duplicated routes, and clients pin to a version and never move.

**Header** (`Accept: application/vnd.api+json; version=2`) — keeps URLs stable,
allows fine-grained negotiation. Cost: invisible in logs and browsers, and easy
for a client to omit.

**No version, additive only** — every change backwards compatible, forever. Cost:
the schema accumulates. Works well far longer than people expect.

Pick one and apply it to the whole surface. A mixed scheme is worse than either.

## Retiring a version

1. **Announce** with a date, in the changelog and in a response header
   (`Deprecation`, `Sunset`).
2. **Measure** who still calls it. Do not guess — there is always one integration
   nobody remembers.
3. **Warn in-band**: a header on every response from the old version.
4. **Brown-out**: fail deliberately for short windows before the cutoff, so
   dependents discover the problem while someone is watching.
5. **Remove.**

Skipping step 2 is how a retirement becomes an incident.

## If you must break something immediately

- Fix forward with a new field and leave the old one populated but documented as
  deprecated.
- Make the new behaviour opt-in via a request field, then flip the default in a
  version bump.
- Never change a field's *meaning* while keeping its name. A field that used to
  mean seconds and now means milliseconds is undetectable to a client and will
  be found in production.
