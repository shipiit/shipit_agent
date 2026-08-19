---
name: Technical Writing
description: Write or edit documentation, a README, a design doc or an explanation so a reader can act on it. Use when producing or improving written technical material.
tools: [read_file, write_file, edit_file, glob, grep]
trigger_phrases: ["write documentation", "write a readme", "improve these docs", "write a design doc"]
version: 1.0.0
---

# Technical Writing

Technical writing has one measure: can the reader do the thing afterwards.
Everything else — completeness, structure, tone — matters only insofar as it
serves that.

## Know which document you are writing

Four kinds, and mixing them is the most common failure:

- **Tutorial** — a beginner completes something concrete. Optimised for success,
  not coverage. No options, no alternatives, no "you could also".
- **How-to** — a competent reader accomplishes a specific task. Assumes
  background, gets to the point.
- **Reference** — a reader looks something up. Complete, consistent, scannable,
  no narrative.
- **Explanation** — a reader understands why. Discusses trade-offs and history.

A README that opens as a tutorial, becomes reference midway and ends in
explanation serves none of the three readers.

## Lead with what it does and who it is for

The first paragraph of anything answers: what is this, who is it for, why would I
use it rather than the alternative. A reader who cannot answer those in ten
seconds leaves, and nothing further you wrote gets read.

## Show, then explain

A working example before the prose. Readers scan for the code block, copy it, and
read the explanation only when it does not work. Write for that order, because it
is what actually happens.

Every example must be complete enough to run. An example with an undefined
variable or an elided import is worse than none: it costs the reader time before
it fails.

## Delete the throat-clearing

Cut on sight: "It is important to note that", "Simply", "Just", "Obviously",
"As you can see", "In order to" (→ "to"), "utilise" (→ "use"). "Simply" and
"just" are the worst — they tell a stuck reader that their difficulty is a
personal failing.

## Prefer the concrete

"Configure the appropriate settings" tells the reader nothing. "Set `timeout` to
at least 30" tells them what to type. If you cannot be specific, you do not yet
understand the thing well enough to document it.

## Document the failure cases

The reader arrives when something is wrong more often than when it is right. What
the common errors mean, what to check first, what is expected behaviour that
merely looks like a bug. This section is used more than the happy path and
written far less often.

## Say what changed and when

Anything with versions needs a changelog entry per user-visible change, and any
statement that will go stale — a version number, a limit, a URL — should be
somewhere it will be updated, not repeated in six places.

## Editing someone else's

Read it once as the intended reader, without fixing anything, and note where you
became confused. Those points are the work. Fix them first; grammar and
consistency afterwards. A grammatically flawless document that loses the reader
in paragraph three has not been improved.
