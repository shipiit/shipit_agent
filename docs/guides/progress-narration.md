---
title: Progress narration
description: A second, cheap model that says what the agent is doing while it does it — decisions before each step, observations after, from observable actions only.
---

# Progress narration

An agent that works in silence for forty seconds looks broken. Progress
narration puts a second model beside the run:

```text
▸ Reading guests.csv to collect the confirmed guests and their plus-ones.
← Three entries: Dana confirmed, Luis confirmed with one, Sam maybe.
▸ Reading venue.txt for the capacity to compare that headcount against.
← The venue seats 3.
▸ Writing a Python script that totals the guests and compares the capacity.
← The script came back with 3 people against a capacity of 3 — they fit.
```

Turn it on per agent:

```python
agent = Agent(
    llm=main_llm,
    progress_summaries=True,
    decision_llm=cheap_llm,     # optional; falls back to `llm`
)
```

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
## What it looks like

<div class="sad">
  <div class="sad-head">progress_summaries=True <span class="sad-badge"><i></i>Live</span></div>
  <div class="sad-body">
    <div class="sad-step"><b>Decision</b>Reading guests.csv to collect the confirmed guests and their plus-ones.</div>
    <div class="sad-row"><span class="sad-g">▤</span><span class="sad-l"><b>Read guests.csv</b> ›<small>✓ read_file · 3.3ms — 4 lines</small></span><span class="sad-n">1 tool · 3.3ms</span></div>
    <div class="sad-step"><b>Observed</b>Dana Kim is confirmed with no plus-ones and Luis Marin is confirmed with one.</div>
    <div class="sad-step"><b>Decision</b>Now reading venue.txt for the capacity to compare that headcount against.</div>
    <div class="sad-row"><span class="sad-g">▤</span><span class="sad-l"><b>Read venue.txt</b> ›<small>✓ read_file · 3.6ms — 1 line</small></span><span class="sad-n">1 tool · 3.6ms</span></div>
    <div class="sad-step"><b>Observed</b>The venue seats 3.</div>
    <div>Three people against a capacity of three — they fit.</div>
  </div>
  <div class="sad-foot">6,985 tokens · claude-opus-5 · narrator: claude-haiku-4.5</div>
</div>

Two models, two jobs: the agent works, and a cheap one says what is
happening. Neither sees the other's private state.

---

## Cost, plainly

Each step adds **one real LLM call before the tools and one after**. A run
that made ten calls makes thirty with narration on. That is why it is off by
default, and why `decision_llm` exists — narration is a job for a small fast
model, not the one doing the work.

```python
Agent(llm=opus, decision_llm=haiku, progress_summaries=True)
```

---

## What the narrator can see

Deliberately little:

- the tools that were selected, and the arguments they were given
- what those tools returned
- the visible messages in the conversation

And deliberately not:

- **the system prompt** — skipped explicitly, so instructions you keep
  private stay private
- **`reasoning_content`** — never read, so a thinking block cannot leak into
  a user-facing string
- **tools** — the narrator is called with `tools=[]`; a narrator that can act
  is not a narrator

Long values are bounded before they are sent, so a 50,000-character tool
result costs a few hundred tokens to describe rather than blowing the
context window.

---

## The events

```json
{
  "type": "agent_decision",
  "payload": {
    "summary": "Reading guests.csv to collect the confirmed guests.",
    "next_action": "call_tools",
    "tools": [{"name": "read_file", "arguments": {"path": "guests.csv"}}],
    "iteration": 1,
    "generated_by_model": true
  }
}
```

```json
{
  "type": "agent_observation",
  "payload": {
    "summary": "Three entries: Dana confirmed, Luis confirmed with one, Sam maybe.",
    "next_action": "evaluate_results",
    "iteration": 1,
    "generated_by_model": true
  }
}
```

A decision with no further tools carries `"next_action": "finish"`.

Both arrive on `agent.stream()` like everything else:

```python
for event in agent.stream(prompt):
    if event.type == "agent_decision":
        print("▸", event.payload["summary"])
    elif event.type == "agent_observation":
        print("←", event.payload["summary"])
```

---

## When narration fails

It never takes the run with it. A timeout, a dead provider, an unparseable
reply — each emits `progress_summary_failed` with the error and the run
continues:

```text
elif event.type == "progress_summary_failed":
    log.warning("no summary: %s", event.payload["error"])
```

---

## How it renders

Decisions and observations are rows of their own everywhere — narration
*about* a run is not the answer *to* the user, and collapsing the two would
say so falsely.

| Surface | Shows |
| --- | --- |
| [Tree](tree-view.md) | `├─ Decision` and `├─ Observed` branches |
| [Live panel](live-ui.md) | An accented step with a `DECISION` / `OBSERVED` label |
| [Timeline](timeline.md) | `agent_decision` / `agent_observation` steps |

---

## Tool groups

With narration on there is prose between every call, and the transcript's
usual rule — prose breaks a work run — would put every single call in a row
of its own. So the runtime declares a **tool group** per iteration, and the
renderers group by it:

```json
{"type": "tool_group_started", "group_id": "tool_group_1", "tool_count": 2,
 "tools": [{"name": "read_file", "call_id": "call_1_1"},
           {"name": "grep_files", "call_id": "call_1_2"}]}
```

Every `tool_called` and `tool_completed` inside carries the same `group_id`,
so a UI can draw one expandable box per iteration — `2 tools · 13.0ms` —
however much was said in between.

A group holds as many calls as the model asked for in that turn. Models that
batch tool calls fill them; models that emit one call per turn produce groups
of one, which is the model's behaviour rather than the renderer's.

---

## The final answer

`final_answer` is emitted just before `run_completed`, so a client does not
have to infer which event carries the answer:

```json
{"type": "final_answer", "payload": {"content": "…", "format": "markdown"}}
```

---

## See also

- [The UI timeline](timeline.md) — the frontend-shaped feed
- [The tree view](tree-view.md)
- [Agent — Streaming](../agent/streaming.md) — the full event vocabulary
