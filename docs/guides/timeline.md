---
title: The UI timeline
description: The runtime's events translated into what a frontend actually draws — reasoning summaries, tool groups, decisions, artifacts and the final answer, as plain JSON.
---

# The UI timeline

`agent.stream()` is the runtime's own vocabulary: every text delta, every
retry, every partial tool argument. That is the right feed for a renderer and
the wrong one for a UI, which draws four things — a summary of what the agent
set out to do, groups of tool calls, the decisions between them, and the
answer.

`timeline()` translates one into the other.

```python
from shipit_agent.narrate import stream_timeline

for step in stream_timeline(agent, "Process the latest RSVP"):
    await websocket.send_json(step)
```

```json
{"type": "run_started",          "goal": "Process the latest RSVP"}
{"type": "tool_group_started",   "group_id": "g1", "title": "Reading 2 files"}
{"type": "tool_call_started",    "tool_call_id": "1", "tool_name": "read_file", "input": {"path": "in.eml"}}
{"type": "tool_call_completed",  "tool_call_id": "1", "status": "completed", "duration_ms": 420, "output": {"from": "jordan@acme.com"}}
{"type": "tool_group_completed", "group_id": "g1", "tool_calls": 1}
{"type": "agent_decision",       "content": "No existing record. Creating one.", "next_action": "call_tool"}
{"type": "final_response",       "content": "RSVP recorded.", "tool_calls": 2, "usage": {"total_tokens": 1180}}
```

For a finished run, `timeline(result.events)` returns the same list.

<style>
.sad{--sad-line:rgba(128,120,112,.28);--sad-accent:#e8590c;--sad-ok:#2f9e44;
--sad-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
border:1px solid var(--sad-line);border-radius:14px;overflow:hidden;
margin:28px 0;font-size:14.5px;line-height:1.6}
.sad-head{display:flex;align-items:center;gap:10px;padding:12px 16px;
border-bottom:1px solid var(--sad-line);font-weight:600;font-size:14px}
.sad-badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
padding:4px 9px;font:11px/1 var(--sad-mono);color:var(--sad-ok);
background:rgba(47,158,68,.12)}
.sad-badge i{width:6px;height:6px;border-radius:50%;background:currentColor;
display:block;animation:sad-pulse 1.4s ease-in-out infinite}
.sad-body{padding:14px 16px}
.sad-body>*{opacity:0;animation:sad-in .45s ease-out forwards}
.sad-body>*:nth-child(1){animation-delay:.15s}
.sad-body>*:nth-child(2){animation-delay:.75s}
.sad-body>*:nth-child(3){animation-delay:1.35s}
.sad-body>*:nth-child(4){animation-delay:1.95s}
.sad-body>*:nth-child(5){animation-delay:2.55s}
.sad-body>*:nth-child(6){animation-delay:3.15s}
.sad-body>*:nth-child(7){animation-delay:3.75s}
.sad-body>*:nth-child(8){animation-delay:4.35s}
.sad-ask{margin:0 0 16px auto;width:fit-content;max-width:76%;
border-radius:14px;padding:9px 14px;background:rgba(128,120,112,.14)}
.sad-step{border-left:2px solid var(--sad-accent);padding:2px 0 2px 12px;
margin:12px 0;opacity:.9}
.sad-step b{display:block;font:10px/1.6 var(--sad-mono);letter-spacing:.08em;
text-transform:uppercase;color:var(--sad-accent);font-weight:500}
.sad-row{display:flex;gap:10px;margin:12px 0;align-items:flex-start}
.sad-row .sad-g{font:13px/1.5 var(--sad-mono);opacity:.55;width:16px;
flex:0 0 16px;text-align:center}
.sad-row .sad-l{flex:1;min-width:0}
.sad-row .sad-l small{display:block;font:12.5px/1.6 var(--sad-mono);opacity:.55}
.sad-row .sad-n{font:12px/1.6 var(--sad-mono);opacity:.5;white-space:nowrap}
.sad-card{display:flex;align-items:center;gap:12px;border:1px solid var(--sad-line);
border-radius:12px;padding:11px 14px;margin:14px 0}
.sad-card .sad-i{width:34px;height:34px;border-radius:9px;flex:0 0 34px;
background:rgba(128,120,112,.14);display:flex;align-items:center;
justify-content:center}
.sad-card b{display:block}
.sad-card small{opacity:.6;font-size:12.5px}
.sad-choices{display:flex;gap:16px;justify-content:flex-end;margin-top:10px;
font-size:13px;opacity:.75}
.sad-choices b{font-weight:600;opacity:1}
.sad-pre{font:12.5px/1.7 var(--sad-mono);white-space:pre;overflow-x:auto;
margin:0;padding:2px 0}
.sad-foot{border-top:1px solid var(--sad-line);padding:10px 16px;text-align:right;
font:12px/1.5 var(--sad-mono);opacity:.55}
@keyframes sad-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes sad-pulse{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){
.sad-body>*{opacity:1;animation:none}.sad-badge i{animation:none}}
</style>
## What your frontend receives

<div class="sad">
  <div class="sad-head">stream_timeline(agent, prompt) <span class="sad-badge"><i></i>Live</span></div>
  <div class="sad-body">
    <pre class="sad-pre">{"type": "run_started",          "goal": "Where did revenue land?"}</pre>
    <pre class="sad-pre">{"type": "tool_group_started",   "group_id": "g1", "title": "Reading bookings.csv"}</pre>
    <pre class="sad-pre">{"type": "tool_call_started",    "tool_name": "read_file", "input": {"path": "bookings.csv"}}</pre>
    <pre class="sad-pre">{"type": "tool_call_completed",  "status": "completed", "duration_ms": 3.3}</pre>
    <pre class="sad-pre">{"type": "tool_group_completed", "group_id": "g1", "tool_calls": 1}</pre>
    <pre class="sad-pre">{"type": "agent_decision",       "content": "Totalling by region.", "next_action": "call_tool"}</pre>
    <pre class="sad-pre">{"type": "artifact_created",     "title": "Revenue by region", "kind": "Page"}</pre>
    <pre class="sad-pre">{"type": "final_response",       "content": "AMER leads at $494K.", "tool_calls": 3}</pre>
  </div>
  <div class="sad-foot">plain JSON · one dict per step</div>
</div>

Every step is a plain dict of primitives — straight onto a socket, with no
serialisation step of your own.

---

## The step vocabulary

| Type | Fields |
| --- | --- |
| `run_started` | `goal` |
| `reasoning_summary` | `content`, `status` |
| `tool_group_started` | `group_id`, `title` |
| `tool_call_started` | `tool_call_id`, `group_id`, `tool_name`, `input` |
| `tool_call_completed` | `tool_call_id`, `status`, `duration_ms`, `output` \| `error` |
| `tool_group_completed` | `group_id`, `tool_calls` |
| `agent_decision` | `content`, `next_action`, `iteration` |
| `agent_observation` | `content`, `iteration` |
| `approval_required` | `action_id`, `tool_name`, `title`, `tag`, `auto_approved` |
| `connection_required` | `connection_id`, `title`, `reason`, `auth` |
| `artifact_created` | `path`, `title`, `kind`, `tool` |
| `sub_agent_tool_call` | `agent`, `task`, `tool_name`, `input` |
| `notice` | `kind`, `content` |
| `final_response` | `content`, `tool_calls`, `usage` |

`status` on a completed call is `completed`, `failed` or `denied`.
`next_action` is `call_tool`, `ask_user` or `finish`.

---

## Three properties it is built to hold

**Causal.** Every step is emitted from information that already exists. A
group's settled title arrives in `tool_group_completed`, never patched back
into a `started` event a client has already drawn — so a row never has to be
undrawn.

**JSON, not objects.** Every step is a plain dict of primitives. It goes onto
a socket, into a log, or through
[`shipit_agent.streaming`](../agent/streaming.md) unchanged. Tool output that
happens to be JSON is parsed, so a UI can render a table rather than a blob;
anything else stays text.

**No hidden reasoning.** `agent_decision` carries prose the model actually
emitted, or a summary generated from observable actions and results — never
`reasoning_content`, never the system prompt.

---

## Wiring a frontend

```python
@app.websocket("/run")
async def run(ws):
    await ws.accept()
    prompt = await ws.receive_text()
    for step in stream_timeline(agent, prompt):
        await ws.send_json(step)
```

```ts
switch (step.type) {
  case "tool_group_started":   openGroup(step.group_id, step.title); break
  case "tool_call_started":    addCall(step.group_id, step); break
  case "tool_call_completed":  settleCall(step.tool_call_id, step); break
  case "agent_decision":       addDecision(step.content); break
  case "artifact_created":     addCard(step); break
  case "final_response":       finish(step.content, step.usage); break
}
```

A crash mid-run still closes open groups: `stream_timeline` finishes the
builder in a `finally`, so a client is never left with a group that never
ends.

---

## The same run as a report

`render_markdown()` prints the timeline as a document — for a PR comment, a
run log, or an audit trail.

```python
from shipit_agent.narrate import render_markdown
print(render_markdown(result.events))
```

```markdown
## Agent Run

**Goal:** Process the latest RSVP

### 1. Tool calls

#### Reading in.eml

##### `read_file`

**Input**

```json
{"path": "in.eml"}
```

**Status:** Completed
**Duration:** 420 ms
```

---

## Raw events instead

If you want everything — token deltas, retries, partial tool arguments —
`agent.stream()` is still there, and every event a timeline step derives from
is in it. See [Agent — Streaming](../agent/streaming.md).

---

## See also

- [The live UI panel](live-ui.md)
- [Progress narration](progress-narration.md) — where `agent_decision` and
  `agent_observation` come from
- [Apps](apps.md) — what produces `artifact_created`
