---
title: The tree view
description: The shape of a run — every call named with its status, decisions marked where they happened, redrawn in place as it grows.
---

# The tree view

The transcript reads like a colleague talking: prose is the content, work is a
quiet receipt underneath. That is right when you are reading the *answer*.

Sometimes you want the opposite — the **shape** of the run:

```text
Agent started
│
├─ Understanding request
│  Read the inbox, check the guest list, then save.
│
├─ Tool group: Read 2 files
│  ├─ read_file                                     completed   4ms
│  └─ read_file                                     completed   6ms
│
├─ Decision
│  Guest was not found. Create a new RSVP record.
│
├─ Approval required
│  Used Slack #events                               comms.send
│
└─ Final answer
   RSVP successfully recorded.

15,470 tokens · claude-opus-5
```

Same rows, same grouping, same verbs as the transcript — only the shape
changes.

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
  <div class="sad-head">agent.run_live(prompt, style="tree") <span class="sad-badge"><i></i>Live</span></div>
  <div class="sad-body">
    <pre class="sad-pre">Agent started
│</pre>
    <pre class="sad-pre">├─ Understanding request
│  Read the inbox, check the guest list, then save.
│</pre>
    <pre class="sad-pre">├─ Tool group: Read 2 files
│  ├─ read_file                                     completed   4ms
│  └─ read_file                                     completed   6ms
│</pre>
    <pre class="sad-pre">├─ Decision
│  Guest was not found. Create a new RSVP record.
│</pre>
    <pre class="sad-pre">├─ Approval required
│  Used Slack #events                               comms.send
│</pre>
    <pre class="sad-pre">└─ Final answer
   RSVP successfully recorded.</pre>
  </div>
  <div class="sad-foot">15,470 tokens · claude-opus-5</div>
</div>

On a terminal this redraws in place: the trunk stays open — `├─ working…` —
until the run ends, and the finished tree replaces the draft exactly once.

---

## Two ways to get one

```python
# Live, in a terminal — redraws in place as the run proceeds
agent.run_live("Process the latest RSVP", style="tree")

# A finished run, as text
from shipit_agent.narrate import render_tree
print(render_tree(result.events, model="claude-opus-5"))
```

In a notebook, `watch(agent, prompt, shape="tree")` draws it in the live
panel.

---

## Live behaviour

On a terminal the tree **redraws in place**: the shape grows downward,
statuses flip from `running` to `completed` where they stand, and the trunk
stays open until the run ends:

```text
├─ Tool group: Reading guests.csv
│  └─ read_file                                     running
│
├─ working…
```

Drawing the final corner early would claim the agent had finished. When the
run closes, the draft is erased and the finished tree is written once, so
your scrollback holds one clean copy rather than every intermediate frame.

Piped output never animates — it gets a single buffered write with no escape
codes, so `> run.txt` is clean.

```python
TreeRenderer(live=True)    # force in-place updates
TreeRenderer(live=False)   # force one buffered write
```

---

## The row labels

| Label | What it is |
| --- | --- |
| `Understanding request` | The opening prose, before any tool ran — what the agent intends |
| `Decision` | Prose between tool groups, or an [`agent_decision`](progress-narration.md) event |
| `Observed` | An `agent_observation` event — what the tools returned |
| `Tool group` | A run of calls, each named with its status and duration |
| `Delegated` | A [sub-agent's](delegation.md) work, attributed to it |
| `Approval required` | A queued side-effecting call |
| `Connection needed` | The agent asking you to connect something |
| `Artifact` | A file the run produced |
| `Final answer` | The last prose in the run |

---

## The deep tree

`detail=True` opens every call — what it was called with, and the first lines
of what came back:

```python
print(render_tree(result.events, detail=True, output_lines=6))
```

```text
├─ Tool group: Searched for def summarize
│  └─ grep_files                                    completed  204ms
│     ↳ pattern='def summarize', path='shipit_agent'
│       shipit_agent/narrate/verbs.py:589:def summarize(name: str, …
```

`output_lines=None` shows every line, at the cost of the tree's compactness.

---

## Alignment

Statuses sit at a fixed column, and nesting is accounted for — a row two
levels deep starts further right, so without that the column would drift and
the fixed column would be pointless. Colour never shifts it either: padding
is computed on visible width, ignoring ANSI escapes.

On a terminal that cannot encode `│├└─`, the tree falls back to `|+-` rather
than raising.

---

## When to reach for it

- **Debugging** — a tool that fired twice is obvious in a tree and invisible
  in prose.
- **Explaining** — "here is what the agent did" pastes cleanly into a PR or a
  ticket.
- **Long autonomous runs** — the live tree is a progress display that does
  not scroll away.

---

## See also

- [The live UI panel](live-ui.md) — the same run as a chat card
- [The UI timeline](timeline.md) — the same run as JSON for a frontend
- [Progress narration](progress-narration.md) — where `Decision` and
  `Observed` rows come from
