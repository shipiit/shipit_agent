# Causes worth checking early

Ordered by how often they turn out to be the answer relative to how quickly they
can be ruled out.

## The state is not what the code assumes

- A value is `None`/`nil`/`undefined` because an earlier call returned nothing on
  a path nobody tested — the empty list, the missing file, the first run.
- A cache is holding a value from before the change. Restart, clear, or check
  the cache key includes what varies.
- Two things share mutable state: a default argument, a module-level object, a
  singleton reused across requests.

## The environment differs

- Works locally, fails in CI: different version, different timezone, different
  locale, different filesystem case-sensitivity, a missing environment variable.
- Works for one user, fails for another: permissions, path, or data shape.
- Worked yesterday: something upstream changed. A dependency, an API, a
  certificate, a token.

## The concurrency assumption is wrong

- Two writers, last one wins, and nobody noticed which order they ran in.
- An `await`/`yield` between a read and the write that depends on it.
- A resource closed by one path while another still holds it.

## The types agree and the meanings do not

- Seconds against milliseconds. Bytes against characters. Zero-based against
  one-based. Local time against UTC.
- An id that is a string in one system and an integer in another, compared with
  `==`.

## The error was already there

- An exception swallowed by a bare `except`, so the real failure happened much
  earlier and quietly.
- A truncated log, a rotated file, a level set above the message you need.

## Ruling out fastest

1. Is the code you are reading the code that ran? (Right file, right branch,
   right container, rebuilt?)
2. Does the failure survive a restart with a clean cache?
3. Does it happen with the simplest possible input?

Most of an hour is saved by asking the first question first.
