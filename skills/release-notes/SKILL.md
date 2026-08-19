---
name: Release Notes
description: Turn a commit range into release notes written for the people who use the software. Use when cutting a release or summarising what changed between versions.
tools: [git_ops, file_read]
trigger_phrases: ["release notes", "changelog", "what changed in"]
version: 1.0.0
---

# Release Notes

Release notes are read by someone deciding whether to upgrade. That is the only
question they answer well, and everything else is noise.

## Gather

Get the commit log for the range. Read the messages, not just the subjects — the
body usually holds the reason, which is the part worth keeping.

## Group by what a user experiences

Not by commit type, and never by author or file:

- **Breaking** — anything requiring action. Always first, even if it is one line.
- **Added** — new capability.
- **Fixed** — a defect a user could have hit.
- **Changed** — behaviour that differs without breaking.
- **Internal** — one line total, or omit. Refactors do not belong here.

## Write each entry for the reader, not the author

Bad: `Refactor TokenCalibrator to use EMA` — describes the change.
Good: `Context compaction now triggers accurately on tool-heavy runs` — describes
what the reader will notice.

If an entry cannot be phrased as something the reader observes, it belongs under
Internal or nowhere.

## Breaking changes need three things

What broke, what to do about it, and — when it is not obvious — why it was worth
breaking. An entry that names the break without the migration is a support ticket
waiting to happen.

## Length

Aim for something readable in under a minute. If the list runs long, the fix is
fewer entries, not shorter ones: merge related commits into one entry that says
what changed overall.
