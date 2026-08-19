---
name: Code Review
description: Review a diff or pull request for correctness, security and maintainability. Use when asked to review, critique, or approve code changes.
tools: [file_read, grep_search, glob_search, git_ops]
trigger_phrases: ["review this pr", "code review", "review my changes"]
version: 1.0.0
---

# Code Review

Read before judging. A review written from the diff alone misses the two things
that matter most: what the changed code is called from, and what invariant it was
upholding before.

## Order of work

1. **Read the diff in full.** Note every changed file, not just the interesting ones.
2. **Read each changed function's callers** (`grep_search` for the name). A signature
   change that compiles can still break a caller's assumptions.
3. **Only then form an opinion.**

## What to look for, in priority order

**Correctness under failure.** The happy path is usually right — it was tested by
hand. Ask what happens when the network call times out, the list is empty, the
file is missing, two of these run concurrently.

**Silent breakage.** A change that makes something fail loudly is safe. A change
that makes something return a wrong answer quietly is not. Flag anything that
swallows an exception, defaults on error, or truncates without saying so.

**Boundary crossings.** Untrusted input reaching a query, a shell, a path, or a
deserializer. Credentials in logs, errors, or fixtures.

**Naming that lies.** A function called `validate_x` that also mutates, a flag
called `safe_mode` that only affects logging. These cost more over time than a
genuine bug, because the next reader trusts the name.

## What not to do

Do not restate the diff. Do not list style preferences a formatter would fix. Do
not raise every possible concern — a review with thirty comments gets none of them
acted on. Pick the three that would actually change the merge decision, and say
plainly which are blocking and which are not.

## Output

For each finding: the file and line, what breaks, and a concrete fix. End with a
one-line verdict — approve, approve with changes, or request changes — and the
single reason for it.
