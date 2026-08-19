---
name: Debugging
description: Find the cause of a defect from a symptom, stack trace or failing test. Use when something is broken and the reason is not yet known.
tools: [bash, read_file, grep, glob, edit_file]
trigger_phrases: ["debug this", "why is this failing", "find the bug", "this is broken"]
version: 1.0.0
---

# Debugging

The failure mode of debugging is not being wrong. It is being convinced too
early: forming a theory from the symptom, finding evidence that fits it, and
spending an hour there while the real cause sits somewhere else entirely.

So the discipline is to postpone the theory until reproduction and evidence are
in hand.

## 1. Reproduce before reading anything

A bug you cannot trigger is a bug you cannot confirm you fixed. Find the exact
command, input or test that fails and run it. If it fails only sometimes, note
how often — an intermittent failure points at concurrency, ordering or external
state, which narrows the search enormously before a single file is opened.

If you cannot reproduce it, say so and ask for what would let you. Do not guess
at a fix for a failure you have never seen.

## 2. Read the whole error

Not the last line. Stack traces are read from the bottom up: the deepest frame
is where it broke, the frames above are how it got there, and the top is usually
your code. The most informative part is often the frame where a value first
became wrong, several frames before the one that raised.

For a wrong-answer bug with no error, the equivalent is finding the earliest
point where a value differs from what it should be.

## 3. Bisect the distance between right and wrong

There is a point where the state is correct and a point where it is not.
Everything is a search for the boundary between them. Halve it:

- Print or log the suspect value at the midpoint of the path.
- Or `git bisect` when the code used to work.
- Or comment out half the input.

Each check should eliminate roughly half of what remains. A check that cannot
eliminate anything is not worth running.

## 4. Confirm the cause before fixing

State the mechanism in one sentence: *"`parse_config` returns `None` when the
file is empty, and `load` does not check, so the attribute access on line 40
fails."* If you cannot write that sentence, you have a correlation, not a cause,
and the fix will be a guess.

The test: you should be able to *cause* the bug deliberately.

## 5. Fix the cause, not the symptom

A `try/except` around the failing line makes the trace disappear and leaves the
bug. Ask what the code should do when the condition occurs — often the answer is
that the condition should have been impossible, and the fix belongs upstream.

## 6. Prove it

Run the reproduction again. Then run the full test suite: the second most common
debugging outcome is a fix that breaks something else. Add a test that fails
against the old code, or the same bug returns in six months.

## What to report

The symptom, the cause in one sentence, the fix, and what you ran to prove it.
If you found other problems while looking, mention them separately — do not fold
unrelated changes into the fix.

See `references/common-causes.md` for the patterns worth checking early.
