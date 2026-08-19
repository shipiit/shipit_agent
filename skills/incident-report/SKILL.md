---
name: Incident Report
description: Write a blameless incident report from logs, a timeline, or notes. Use after an outage, security event, or production failure.
tools: [file_read, grep_search]
trigger_phrases: ["incident report", "postmortem", "write up the outage"]
version: 1.0.0
---

# Incident Report

The report exists to change something. A report that describes an outage
accurately and changes nothing has failed, however well written.

## Structure

**Summary** — three sentences: what broke, who was affected, how long. Written so
someone who reads only this paragraph is not misled.

**Timeline** — timestamps in one timezone, stated explicitly. Include detection and
each mitigation attempt, including the ones that did not work; those are often
where the real lesson is.

**Impact** — measured, not adjectival. "Roughly 4% of requests failed for 22
minutes" rather than "brief degradation". If the number is unknown, say it is
unknown and why.

**Root cause** — the condition that made the failure possible, not the action that
triggered it. A deploy that exposed a missing timeout is a deploy that revealed
the cause; the missing timeout is the cause.

**Contributing factors** — what made it worse or slower to find. Absent
monitoring, a misleading alert, an undocumented dependency.

**Actions** — each with an owner and a date. An action without both is a wish.

## Blameless means specific, not vague

Blameless does not mean omitting what happened. It means describing the system
that allowed a reasonable person to make that choice. "An engineer deployed
without running migrations" is blame. "Deploys do not check for pending
migrations, and nothing in the process surfaces them" is the same fact, pointed at
the fixable thing.

## What to leave out

Speculation presented as fact. Individual names. Anything that would embarrass a
person rather than inform a reader. Mark genuine uncertainty as uncertain — a
report that overstates confidence gets its actions ignored the next time it is
wrong.
