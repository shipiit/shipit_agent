---
title: The live UI panel
description: A chat card that redraws in place while the agent works — tokens, tool rows with real output, approval and artifact cards, tokens footer.
---

# The live UI panel

`agent.run_live()` prints a transcript to a terminal. `watch()` draws the
same run as an **HTML card that redraws in place** — in a Jupyter cell, or
anywhere you can render HTML.

```python
from shipit_agent.narrate import watch

answer = watch(agent, "Which accounts are at risk this quarter?")
```

While the run proceeds the card updates: tokens land with a caret, tool rows
appear in flight and settle, each call folds away with the bytes it actually
returned, approval and artifact cards interrupt the flow, and the footer
counts tokens.

It is fed the same `WorkRunAccumulator` as every other renderer, so a row
reads identically in the terminal, in a shared HTML file and here. Only the
shape changes.

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
  <div class="sad-head">RSVP intake <span class="sad-badge"><i></i>Live</span></div>
  <div class="sad-body">
    <div class="sad-ask">Which of the three people who replied are not yet on the guest list?</div>
    <div class="sad-row"><span class="sad-g">⌕</span><span class="sad-l"><b>Searched for inbox/*.eml, read 4 files</b> ›<small>inbox/*.eml · guests.csv · msg-1.eml · msg-2.eml</small><small>✓ glob_files · 4ms — 3 lines</small></span><span class="sad-n">4 tools · 21.0ms</span></div>
    <div>The following people who replied are not on the guest list:</div>
    <div class="sad-row"><span class="sad-g">✎</span><span class="sad-l"><b>Wrote summary.md</b> ›<small>summary.md</small></span><span class="sad-n">1 tool · 3.2ms</span></div>
    <div class="sad-card"><span class="sad-i">▤</span><span class="sad-l"><b>RSVP summary</b><small>Doc · Click to open</small></span><span style="opacity:.5">↗</span></div>
  </div>
  <div class="sad-foot">14,317 tokens · claude-opus-5</div>
</div>

Each row above is one thing the runtime emitted. Click a `✓ glob_files · 4ms`
line in a real panel and the tool's actual output opens underneath it.

---

## The three surfaces

| Call | What you get |
| --- | --- |
| `watch(agent, prompt)` | Live card, redrawing; returns the final answer |
| `watch(agent, prompt, shape="tree")` | The same, drawn as a [tree](tree-view.md) |
| `render_chat_html(events)` | A finished run as an HTML fragment |

`render_chat_html` takes an `AgentResult`, a list of events, or anything
iterable of events, and returns a self-contained fragment (styles included)
you can drop into a page.

```python
from shipit_agent.narrate import render_chat_html

result = agent.run("Summarise the inbox")
html = render_chat_html(result.events, model="claude-opus-5", title="Inbox")
```

---

## Options

```python
watch(
    agent,
    prompt,
    title="RSVP intake",      # heading on the card
    shape="chat",             # or "tree"
    show_output=True,         # fold each call's real output behind it
    output_limit=None,        # None = every byte; default 4000 chars
    min_interval=0.05,        # redraw throttle for token deltas
)
```

### `output_limit=None`

The default clips a tool's output at 4,000 characters. `None` shows every
byte — each output scrolls in its own box, so a long file costs height inside
that box rather than in the page.

### Throttling

A full re-render per token is O(n²) DOM churn, and it stutters exactly when
the answer gets long. Structural events — a call starting, an approval
landing, the run finishing — always flush immediately; token deltas flush on
a time budget. `min_interval=0` disables the throttle if you want every
token painted.

---

## What a row looks like

```text
  ⌕  Read 3 files, searched for renewal_date          3 tools · 14.0ms
     accounts.csv · tickets.csv · usage.csv
     ✓ read_file · 4ms — 128 lines        ← click to open the real output
```

- **Verb and target**, not a tool name — `Read accounts.csv`, not
  `read_file({"path": …})`. See [the Narrator](../agent/streaming.md).
- **Consecutive calls collapse into one row.** Prose breaks the run; so does
  a tool group the runtime declared.
- **`3 tools · 14.0ms`** on the right: how many calls the row stands for and
  how long they took together.
- **Each call folds away** with its real output behind it. Nothing is
  summarised — the bytes are there.

---

## Cards

Some rows are not work. They interrupt, because they are the thing you have
to read in order to answer:

| Row | Drawn when |
| --- | --- |
| Approval | A side-effecting call was queued — `Always approve · Deny · Approve` |
| Connection | The agent asked you to connect something, with its reason |
| Artifact | A tool produced a file — `Q2 Kickoff Brief · Doc · Click to open` |
| Decision / Observed | [Progress narration](progress-narration.md), when enabled |
| Note | Lockdown engaged, context compacted, guardrail triggered |

See [apps](apps.md) for artifacts and [connections](connections.md) for the
connect card.

---

## Styling and safety

Every selector is scoped under `.sa-live`. Notebook output shares one
document with the whole page, and a bare `body { … }` rule would restyle the
user's notebook; a test walks the stylesheet to keep it that way.

The card is theme-aware — it follows `prefers-color-scheme` — and every value
that comes from a model, a tool or a filename is HTML-escaped.

---

## Using it outside a notebook

`LiveView` is the class behind `watch`. With `display=False` it never touches
IPython, so it works in a web app, a test, or a script:

```python
from shipit_agent.narrate import LiveView

view = LiveView(prompt=prompt, model="claude-opus-5", display=False)
for event in agent.stream(prompt):
    view.feed(event)
    socket.send(view.html())      # or push only on structural events
view.close()
```

For a frontend you usually want [the timeline](timeline.md) instead — JSON
steps rather than rendered HTML.

---

## See also

- [The tree view](tree-view.md) — the shape of a run rather than its prose
- [The UI timeline](timeline.md) — the events a frontend draws
- [Progress narration](progress-narration.md) — decisions and observations
- [Apps](apps.md) — artifacts, and the cards they produce
