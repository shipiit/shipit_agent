# Making SHIPIT Agent a Cloudflare-OS-class agent

**Status:** design doc, pre-implementation.
**Reference:** `others/_reference_cloudflare_os` — Cloudflare OS v2, MIT-adjacent open source, ~412k LOC TypeScript, pnpm monorepo.
**Target:** `others/shipit_agent` — SHIPIT Agent v1.0.18, ~49.5k LOC Python, 122 test files.

---

## 0. The thesis, in one paragraph

Cloudflare OS is not "a chat UI with nicer CSS." Its output feels calm because of four architectural decisions that happen *before* anything is rendered: (1) every tool call is narrated as a **human verb and target**, never a tool name; (2) consecutive tool calls with no prose between them **collapse into a single row**; (3) tool calls are split into **observations** (read-only, near-invisible) and **actions** (side-effecting, reviewable, queued); (4) the model is given **14 tools, not 50**, with `executeCode` as a universal escape hatch and *progressive discovery* to learn APIs on demand. The polish in the screenshots is the visible consequence of those four. SHIPIT can adopt all four — three of them without touching the runtime loop.

**Stage table:**

| Stage | What | Touches runtime? | Risk | Effort |
|---|---|---|---|---|
| **1** ✅ | The Narrator — verbs, grouping, live renderer, HUD | No. Presentation over existing events. | Low | **landed** |
| **2** ✅ | Tool contracts + observation/action split + deferred approval queue | Yes — both runtimes, via one shared gate | Medium | **landed** |
| **3** ✅ | Streaming tool-input parser, checkpoint compaction, `give_up` | Yes | Medium | **landed** |
| **4** | Code-mode + progressive discovery (the 50→14 tool collapse) | Yes, deeply | High | ~2 weeks |
| **5** | Surfaces — TUI, SSE/web parity, shareable run artifacts | No | Low | ~3 days |

Stages 1, 3, and 5 are independent. Stage 2 gates stage 4.

---

## 1. Screenshot anatomy

Reading the four reference screenshots literally, top to bottom. Every element maps to a mechanism described later.

### 1.1 "Accounts at risk this quarter"

```
 ⌕  3 resource reads                                        ›
    Enterprise Accounts · Open Tickets · Usage by Account

    ┌──────────────────────────────────────────────────┐
    │ 📊 BigQuery — analytics.usage       ✓ Connected  │
    │    Read the usage tables                         │
    └──────────────────────────────────────────────────┘

 Let me look at usage trends, open tickets and renewal dates together.

 ❯_ Ran code const risk = scoreAccounts(usa…            ›

 Three I would put on your list:
   • Northwind: usage down 38% since March, renews in six weeks.

                                       18,240 tokens · $0.12
```

Seven observations:

1. **Three tool calls became one line.** Not three cards. `3 resource reads` with the targets on a dim second line, dot-separated, monospace.
2. **The verb is past tense and human.** "Ran code", not `executeCode(code="...")`.
3. **The code target is the first line of the code, elided at ~60 chars.** `const risk = scoreAccounts(usa…` — enough to recognize, not enough to dominate.
4. **Prose is the primary content.** Tool rows are grey, small, secondary; the model's sentences are full-size black. The transcript reads as a colleague talking, punctuated by receipts.
5. **`›` on every row** — everything is expandable, nothing is expanded by default.
6. **The connection card is an exception** — a real bordered card, because it's a *state change* the user must notice ("Connected"), not a step.
7. **The footer is the whole run's accounting**, right-aligned, monospace, dim: `18,240 tokens · $0.12`.

### 1.2 "Inbox Triage" — the approval card

```
 ⚯ Listed connectable resources                        ›
   gmail · events@acme.com

 I'll make it a workflow: the inbox triggers it, an agent reads
 the reply, the row gets written.

 ❯_ Ran code self.on("email", async (msg) => { …        ›
 ⚯ Used the app

 Running. Only the classify step needs a model, so it costs
 almost nothing per email.

 ● Email the 42 confirmed guests
   ┌────────────────────────────────────────────────┐
   │ Send the venue change notice to everyone who   │
   │ replied Yes.                                   │
   │ gmail · events@acme.com                        │
   └────────────────────────────────────────────────┘
              Always approve    Deny    Approve
```

The approval is **inline in the transcript**, not a modal, not a blocking terminal prompt. Three affordances, and the order matters: `Always approve` (leftmost, quiet), `Deny`, `Approve` (rightmost, emphasized). The pending action's description is **never collapsed** — it's the thing the user has to read to decide, so hiding it behind a disclosure would add a step before every decision (`ChatInterface.tsx:6242-6244`, verbatim rationale in their comment).

Crucially the agent **did not stop**. The prose after the approval card ("Running. Only the classify step needs a model…") was written *while the action sat pending*. That's §2.7.

### 1.3 "Q2 kickoff pack" — artifacts as first-class rows

```
 ⌕ 2 resource reads                                    ›
   Product Roadmap Q2 · Customer Commitments
 📖 Read from knowledge: Brand Guidelines                ›

 I'll start with the brief, pull the workstreams into a tracker,
 then build the deck from both.

 Brief is written — it reads from the roadmap, so it stays right
 when that changes.

   ┌──────────────────────────────────────┐
   │ 📄 Q2 Kickoff Brief                ↗ │
   │    Doc · Click to open               │
   └──────────────────────────────────────┘
```

Deliverables get a **card with a noun and an icon derived from the artifact's declared format**, not from the tool that made it. `Created Doc` / `Created Sheet` / `Created gadget` — the noun comes from the blueprint's `output.noun` (`ChatInterface.tsx:655-658`).

### 1.4 The header

`$0.09` live-updating cost · activity icon · share · presence avatars. Cost is ambient and always visible, not a thing you go look up.

---

## 2. How Cloudflare OS actually works

Mechanism-level, with references. This is the part worth stealing.

### 2.1 Two message streams, not one

The single most important structural idea, and the one SHIPIT is missing.

| | **Canonical log** | **Provisional stream** |
|---|---|---|
| Source | `AiChatMessage[]`, durable, sequence-numbered | `AiChatStreamEvent`, ephemeral |
| Written | once per completed model turn (the "persistence barrier", `agent.ts:2910`) | continuously, as tokens arrive |
| Lifetime | forever; pages back through history | discarded the moment the durable message lands |
| Purpose | truth, replay, revert, compaction | *what it looks like right now* |

The UI renders provisional state **on top of** the canonical log, and throws it away when the real message arrives (`ChatInterface.tsx:5048-5061`). A `streamGeneration` counter (`api.ts:2359`) detects server restarts: if the generation changed, in-flight provisional state is garbage and gets cleared, because the turn will re-stream from scratch.

**Why it matters for SHIPIT:** shipit's `AgentEvent` stream is a single flat log where "started" and "completed" are separate append-only entries. There is no notion of a row that *updates in place* from `Reading app.py` → `Read app.py`. Every modern-feeling transition in the screenshots is an in-place update. This is the design problem stage 1 must solve (§4.1.3).

### 2.2 The stream event vocabulary

`workshop-shared/src/api.ts:2283-2342` — 14 event types, and the discipline is worth noting: each one exists because the UI needs to change *one specific thing* before the durable message lands.

| Event | Payload | Why it exists |
|---|---|---|
| `textDelta` | `delta` | prose types out |
| `reasoningDelta` | `delta` | thinking traces, separately toggleable |
| `toolCallStarted` | `toolCallId`, `toolName` | draw the provisional row *now*, present tense, before args are known |
| `toolCodeDelta` | `toolCallId`, `delta` | `executeCode` only — the code appears as the model writes it |
| `toolCallFinished` | `toolCallId` | stop the spinner; row is no longer "in progress" |
| `toolCallTarget` | `toolCallId`, `file` | the row can name its file before the call finalizes |
| `toolCallOutputFormat` | `toolCallId`, `output` | a `createGadget` row can say "Creating Doc" not "Creating gadget" |
| `toolOutputDelta` | `toolCallId`, `delta` | long-running tool output streams into the row |
| `setActiveFile` | `file \| null` | the editor pane follows the agent |
| `codeReset` / `codeUpdate` | Y.Doc update | live CRDT preview of the file being written |
| `compacting` / `compacted` | `nothingToCompact?` | context compaction is *visible*, not a silent stall |

Note what is **not** here: no "iteration started", no "step". The user is never shown the loop's internal structure. SHIPIT currently emits `step_started` with an `iteration` number, which is a runtime concept leaking into the transcript.

### 2.3 The provisional state machine

`ChatInterface.tsx:4128-4211`.

```ts
type ProvisionalToolCallState = {
  toolCallId: string;
  toolName: string | null;      // null until toolCallStarted lands
  target?: string;              // from toolCallTarget, or parsed from streaming input
  outputFormat?: BlueprintOutput;
  code: string;                 // accumulated toolCodeDelta
  output: string;               // accumulated toolOutputDelta
  finished: boolean;
};

type ProvisionalChatState = {
  text: string;                 // accumulated textDelta
  reasoning: string;
  compacting: boolean;
  toolCalls: ProvisionalToolCallState[];
  toolCallsById: Map<string, ProvisionalToolCallState>;
  codeUpdates: Uint8Array[];
  activeEditingFile: ActiveFileTarget | null | undefined;
};
```

Two independent clear points, and the comment at `:4164` explains why: **chat state clears once per step** (when a message arrives), **code state clears once per turn** (when changes arrive). Conflating them makes the editor flicker between tool calls.

### 2.4 The grouping rule

This is the rule that produces the calm transcript, and it is remarkably simple.

> **Consecutive assistant messages that have tool calls but no visible prose merge into one "work run." Prose breaks the run.**

`ChatInterface.tsx:3502-3530` (`getWorkOnlyMessageParts`) and `:3535` (`appendWorkParts`). An assistant message with empty text and ≥1 tool call is *work*; an observation action-log entry is *work*; anything with text is not. Runs of work accumulate, then `buildToolCallGroups` (`:941-1000`) renders the accumulation as one row.

The label construction (`:948-985`):

```
1 call                      → "Read app.py"                     (verb + target)
n calls, 1 distinct tool    → "Read 3 files"                    (count-aware)
   …unless all share one target and there are no observations:
                            → "Read app.py"
n calls, ≤3 distinct tools  → "Read 3 files, made 2 edits, ran code"
n calls, >3 distinct tools  → "7 tool calls"
+ observations              → append ", 4 resource reads"
```

Then: first part keeps its capital, every subsequent part is lower-cased (`lowerFirst`, `:963`). That one line is why it reads as a sentence and not a list.

Detail lines are the **deduplicated union of all targets**, joined with ` · `, monospace, dim — and shown **only when there is more than one** (`:1693`). A single-target group already has its target in the label; repeating it would be noise.

The group key is the **first tool call's id** (`:986`) — deliberately, so that expansion state survives the provisional→committed transition. Expand a row while it's streaming and it stays expanded when the real message lands.

### 2.5 The verb system

`ChatInterface.tsx:626-700` (`getToolCallSummary`), `:741` (`describeToolCallCount`), `:806` (`getProvisionalToolLabel`), `:856` (`getProvisionalToolVerb`), `:876` (`describeProvisionalToolCount`).

Four parallel tables, one per grammatical need:

| Need | Example |
|---|---|
| past + target | `Read app.py` |
| past + count | `Read 3 files` |
| present + target | `Reading app.py` |
| present + count | `Reading 3 files` |

Plus per-tool **target extraction** with real logic, not just "first argument":
- `executeCode` → first non-blank line of `code`, elided at 60 chars (`:659-672`)
- `webFetch` → the URL's **host**, not the URL (`:675-683`)
- `setBindingHook` → `bindingName → entrypoint`
- `createGadget` → the *blueprint's noun*, so it says "Created Doc" (`:655`)

They can afford an exhaustive `never` check (`:697`) because they have 14 tools. **SHIPIT cannot** — 50 built-ins plus arbitrary MCP tool names. Our version must be a dict with a humanizing fallback (§4.1.1).

### 2.6 Observations vs actions — the security model that produces the UI

`workshop-shared/src/gatekeeper.ts:904` (`ObservationDescription`) and `:974` (`ActionDescription`).

Every operation through a Gatekeeper is one of two things:

**Observation** — read-only. Must be *authorized* before data returns, but runs immediately. Carries `title`, markdown `description`, and two policy fields: `prohibitAllSharing` (this data is so sensitive that observing it puts the gadget into lockdown — it may never act again, only observe, so it cannot exfiltrate) and `excludeObservers` (specific users must not see this).

**Action** — side-effecting. Submitted to an approval queue, **not performed** until approved. Carries:

| Field | Meaning |
|---|---|
| `title` / `description` | one-line + full markdown, for the human reviewing |
| `implementsRevert` | can the UI offer undo? |
| `awaitDecision` | **hint that the agent must stop and wait** — set only when the gatekeeper does *not* simulate |
| `autoApprovable` | the author's per-action verdict that this specific call is safe to auto-apply |
| `actionKind: {tag, label}` | stable machine tag for policy, human label for UI |

The UI split falls straight out: observations collapse to `3 resource reads`; actions get a card with buttons. **The presentation is downstream of the security model.** You cannot get the former without the latter.

### 2.7 Deferred approval with simulation — the genuinely novel idea

From their README, and it is the single best idea in the repo:

> Traditionally, human-in-the-loop setups require the human to approve actions *synchronously*. […] you give your agent a task, then walk away and get a coffee, only to come back and find the agent got stuck on an approval on the first step. As a result, people often give in and set their agents to "auto-approve", or `--dangerously-skip-permissions`, which is, obviously, unsafe.

Their fix: the Gatekeeper **simulates** the un-approved action locally. It tells the agent the action completed; subsequent reads return the simulated post-action state. The agent keeps working and queues more dependent actions. The human approves **later, in bulk or one by one** (`gatekeeper.ts:617-623`).

`awaitDecision` is the escape valve: a gatekeeper that *can't* simulate sets it, and the harness suspends the turn (`gatekeeper.ts:996-1008`, and the comment is worth reading — an agent that keeps going against unsimulated state "tends to get confused: re-trying, second-guessing, or undoing its own work").

**Auto-approval** (`auto-approval.ts`) is a per-`actionKind.tag` rule, and the drain algorithm has two properties worth copying exactly:

1. It applies pending actions **in ascending id order** and **stops at the first non-eligible one** — never skips ahead of a manual gate. (`#drainOnce`, `:57-92`.)
2. Eligibility requires **both** signals: the author's per-action `autoApprovable` **and** a user-enabled rule for the tag. Neither alone suffices.
3. Per-gatekeeper single-flight with a rerun flag, because the DO's input gate is open across the apply `await`.
4. Auto-approvals are attributed to **the user who enabled the rule** — they run under that person's authority.

### 2.8 Streaming tool-input parser

`streaming-json-parser.ts` — an incremental JSON parser with **O(n) total cost** that streams *one designated string field* while the tool call's arguments are still arriving.

```ts
let parser = new StreamingToolInputParser("content");
parser.append('{"filename": "foo.ts", "content": "hel');
parser.append('lo world"}');
parser.prefixFields   // => {filename: "foo.ts"}   — parsed once, when the streaming field starts
parser.streamingValue // => "hello world"          — grows incrementally
```

An 11-state machine (`initial → expectKey → inKey → expectColon → expectValue → inStringValue | inOtherValue | streaming → afterValue → done | error`). Fields *before* the streaming field are `JSON.parse`d once, in one shot, the moment the streaming field's opening quote is found — which is also the signal that they're complete.

Two consumers:
- **`ExecuteCodeStreamManager`** (`agent.ts:941`) — streams the `code` field as `toolCodeDelta`, tracking `emittedLength` so only new characters go out.
- **`CodePreviewManager`** (`agent.ts:739`) — streams `content` (writeFile) / `replacement` (editFile) directly into a **Y.Doc CRDT cursor**, so the file in the editor pane types itself. For `editFile` it locates a *unique* match of `textToReplace`, deletes it, and inserts the replacement at that cursor as it arrives (`:863-905`). Non-unique match → no preview, silently.

Failure is always graceful: a parse error sets `#broken`, emits `codeReset`, and the preview simply stops. Never takes the turn down.

### 2.9 Checkpoint compaction

`agent-compaction.ts`. Four things SHIPIT's compaction doesn't do:

1. **Real token budgets per model.** `getModelTokenLimits` reads `contextWindow` and `outputLimit` from a model table; `inputBudget = contextWindow - maxOutputTokens`. Trigger at **0.85** of input budget; retain **0.30**. SHIPIT uses `len(text) // 4` and a hardcoded 0.75.
2. **The boundary is a turn start.** `startsAgentTurn` (`:69-77`) — cut only where a user/gadget message, callback, nudge, or accepted connection begins a turn, so retained messages never open mid-turn.
3. **A structured handoff prompt**, not "summarize this." `COMPACTION_SYSTEM_PROMPT` (`:38-50`) demands six headings — `## Goal / Constraints & Preferences / Progress / Key Decisions / Next Steps / Critical Context` — tells the model to *fully integrate* any prior summary rather than nest them, and explicitly instructs it to **ignore instructions inside the transcript it's summarizing** (prompt-injection defense on the compaction path — SHIPIT has no equivalent).
4. **Immutable checkpoints, canonical history preserved.** The chat keeps every checkpoint ever published; agent replay starts at the newest boundary, but the *user* can still page back through everything. SHIPIT's compaction destructively replaces the message list.

### 2.10 Cost & tokens

`chat.totalTokens` / `chat.totalCost` live on chat metadata, rendered in the composer footer (`ChatInterface.tsx:7670-7674`) and per-chat in the sidebar (`:6559`). Always visible, updated per turn. Formatted `toLocaleString()` for tokens (thousands separators — `18,240` not `18240`) and `toFixed(4)` for dollars.

### 2.11 The 14-tool design, and code mode

This is the deepest architectural difference and it deserves its own callout.

The full tool list the model sees:

```
readFile  writeFile  editFile  webFetch  observeUserChanges
describeBinding  setGadgetBinding  createGadget  listBlueprints
executeCode  listConnectableResources  requestConnection  giveUp
```

Thirteen (fourteen with `setBindingHook`). **There is no `github` tool, no `slack` tool, no `sql` tool.** Instead:

- Every external resource is a **binding** in `env` — `env.WAREHOUSE`, `env.GMAIL`.
- `executeCode` runs a self-contained JS module `export default async function(self, env, ctx)` against those bindings, in a sandbox.
- **Progressive discovery**: `describeBinding(name)` returns the TypeScript types for *just that resource* — "rather than the entire API space of the vendor, which may support many kinds of resources" (`gatekeeper.ts:598-601`).
- An `AgentCatalog` (`agent-catalog.ts`) gives a *bounded, sorted, re-validated* index of what's reachable through a binding, folded into the system prompt so the agent knows what exists without paging.

The consequences:
- The tool schema block stays tiny regardless of how many integrations are installed. SHIPIT's 50 tools cost thousands of prompt tokens on **every** call.
- New integrations require zero prompt changes.
- The agent composes: one `executeCode` can join BigQuery to Gmail. SHIPIT would need the model to orchestrate five tool calls and hold intermediate results in context.
- The catalog is **re-validated workshop-side** (`normalizeAgentCatalog`) because gatekeeper output is untrusted — control chars stripped, entries sorted, clamped to bounds. Defense in depth against a compromised connector injecting into the prompt.

Sub-agents get an even narrower set: `{describeBinding, executeCode, giveUp}` (`agent.ts:2830-2838`).

### 2.12 Smaller things worth stealing

- **`giveUp` as a real tool** (`agent.ts:2818`) with a required `error` string. An agent that can't proceed says so *structurally* instead of emitting prose and stalling. SHIPIT infers stalls heuristically from phrases like "let me" (`runtime.py:97-108`) — a real tool is strictly better.
- **The persistence barrier** (`agent.ts:2910`): exactly one durable log entry per completed model turn, and the loop **awaits** it before the next request. The log can never fall behind what the model has seen. SHIPIT appends messages ad hoc mid-loop.
- **Honest failure on abort** (`agent.ts:2946-2952`): a tool call the cancellation pre-empted is recorded as `error: "Operation aborted"` — "so replay shows the model an honest failure rather than a fabricated success (or a missing tool result, which providers reject)." SHIPIT does this correctly already (`runtime.py:540-554`).
- **Turn cap, not step cap**: `turnCount` replacing `stepCountIs(30)`.
- **Format blueprints as committed data** — the deployment's output presentations ship as `.gadget` archives + JSON sidecars, globbable and fork-overridable via `FORMAT_BLUEPRINTS_DIR`.
- **Slash commands are provider-supplied** (`slash-commands.ts`), collected from every attached gatekeeper and merged into one sorted catalog. SHIPIT's are files in `.shipit/commands/`.

---

## 3. Where SHIPIT stands — honest gap table

| Capability | Cloudflare OS | SHIPIT today | Gap |
|---|---|---|---|
| Tool call → human verb | 4 tables, per-tool target logic | `⚙ bash(command="pytest -q")` — raw name + args (`activity.py:57`) | **Total** |
| Grouping | work-runs collapse to one row | one card per call, always | **Total** |
| In-place row update | provisional → committed | append-only; `tool_called` then `tool_completed` print as two lines | **Total** |
| Observation/action split | core security model | `read_only` attr exists, used only by permissions (`permissions.py:108`) | Partial foundation |
| Approval | inline card, deferred, bulk, auto-by-tag | blocking `[y]/[n]/[a]` prompt (`hitl.py`) | **Total** |
| Streaming tool input | `StreamingToolInputParser` + CRDT preview | none — args arrive whole | **Total** |
| Compaction | checkpoints, real budgets, structured handoff, injection-safe | destructive, `len//4`, generic prompt (`runtime.py:576-672`) | Large |
| Cost HUD | live, always visible | `CostTracker` exists but isn't rendered live | Small |
| `give_up` tool | real tool | phrase-matching heuristic (`runtime.py:97`) | Small |
| Tool count in prompt | 14 + progressive discovery | 50 schemas every call | **Large** |
| Stream event vocabulary | 14 purpose-built | 21 `EventType`s, and 2 emitted types (`tool_denied`, `text_delta`) **aren't in the Literal** | Small + a bug |

**Assets SHIPIT already has** that make this cheaper than it looks: a full `AgentEvent` stream with `call_id` correlation and `duration_ms`; `text_delta` inline streaming with adapter capability sniffing (`llms/base.py:36`); a `read_only` tool attribute; `CostTracker` with a real pricing table; `PermissionEngine` with `updated_arguments` rewriting; `StreamRenderer` already handling TTY/non-TTY.

---

## 4. The plan

### Stage 1 — The Narrator ✅ LANDED

Pure presentation. New package `shipit_agent/narrate/` (1,273 lines) + 780 lines of
tests. **2,144 tests pass, 0 failures.** Verified end-to-end against a real `Agent`
with real built-in tools:

```
  ⌕ Read 2 files, searched for renewal_date ›
    billing/accounts.py · billing/usage.py · renewal_date

Let me look at usage trends, open tickets and renewal dates together.

  ❯ Ran code const risk = scoreAccounts(usage, tickets, renewals) ›

Three I would put on your list:
  - Northwind: usage down 38% since March, renews in six weeks.

                                             18,240 tokens · claude-opus-5
```

**Four bugs the work shook out**, all fixed:

1. **Verb/noun collision in count labels** — composing `past + noun` gives
   `Edited 3 edits`, `Queried 3 queries`, `Read PDF 2 PDFs`. Fixed with a
   `count_verb` override on `VerbSpec` (`Made 3 edits`, `Ran 3 queries`); a test
   asserts no label repeats a word stem, across all 50 built-ins.
2. **Dangling prepositions** — a tool appearing *once* inside a multi-tool run
   rendered as the bare verb: `Read 2 files, searched for`. Now a lone call keeps
   its target. Test asserts no composite label ends in a preposition.
3. **`tool_denied` carried no `tool` or `call_id`** (`runtime.py:340` **and**
   `async_runtime.py:222` — the same bug in both runtimes) — renderers pair
   outcomes to calls by those keys, and the permission gate fires *before*
   `tool_called`, so a blocked call was invisible. Both fixed.
4. **`EventType` Literal was stale** — `tool_denied` and `text_delta` were emitted
   but undeclared. Fixed alongside the two new types.

**Nothing is a fixed list.** The 50 built-in specs are *defaults*. Any project can
teach the Narrator its own vocabulary, or re-narrate a built-in:

```python
from shipit_agent.narrate import VerbSpec, register_verb

register_verb("deploy_service",
              VerbSpec("Shipped", "Shipping", "✚", noun="service", args=("service",)))
# → "Shipped billing-api" / "Shipping billing-api" / "Shipped 3 services"
```

Resolution order is registrations → built-in table → humanizing fallback, and it
is the same order everywhere including `is_read_only`, so a registration can't
half-apply.

**Runtime touched: 4 lines**, all additive — the `tool_denied` payload fix, and a
`usage_tick` emit after `_track_usage` so the footer can update mid-run. No
semantics changed.

**Design decision — live vs. buffered.** A terminal can't un-print, so the
in-place present-tense row (`Reading app.py` → `Read app.py`) is a `LiveRegion`
that rewinds exactly the lines it drew (`\033[NA\033[J`). Off a TTY it's inert and
the renderer buffers, emitting only the settled past-tense row — byte-stable, no
escape codes. A golden test pins the piped output.

**Adaptation, not transcription.** Cloudflare's `describeToolCallCount` can be an
exhaustive `never`-checked match over 14 tools. We have 50 built-ins plus
open-ended MCP names, so the registry is a dict with a real morphology fallback:
irregular pasts, consonant-doubling rules (`run→running` but `send→sending`), and
`server__do_thing` prefix stripping. Verified across 36 realistic MCP tool names.

The `3 resource reads` phrasing is kept for exactly the case where it's true — a
run of >3 *distinct* tools that were all read-only. Three `read_file` calls read
`Read 3 files`, which is strictly more informative.

#### 4.1.1 `narrate/verbs.py` — the verb registry ✅ *drafted*

**Status: written, ready for review** at `shipit_agent/narrate/verbs.py`.

Public surface:

```python
summarize(name, arguments) -> ToolSummary   # .past_label() / .present_label()
describe_count(name, n)         -> "Wrote 5 files"
describe_count_present(name, n) -> "Writing 5 files"
icon_for(name)                  -> glyph
is_read_only(name, tool)        -> bool
```

Three layers, in priority order: a hand-written `VerbSpec` per built-in (50 entries); per-tool target extractors (first code line, URL host); and a **humanizing fallback** — `search_issues` → *Searched issues*, with irregular-verb tables and MCP `server__tool` prefix stripping. The fallback is non-negotiable: MCP tool names are unbounded, so an exhaustive match like Cloudflare's would crash on the first unknown server.

`is_read_only` delegates to a tool's own `read_only` attribute first, then the spec table, then `PermissionEngine.is_read_only` — same precedence order the permission engine already uses, so the two can never disagree.

#### 4.1.2 `narrate/grouping.py` — the work-run engine

Port §2.4's rule. Input: a list of `AgentEvent`. Output: `list[TranscriptRow]` where a row is prose, a work group, an approval, or a status line.

```python
@dataclass(frozen=True, slots=True)
class WorkGroup:
    key: str                  # first call_id — survives provisional→committed
    icon: str
    label: str                # "Read 3 files, made 2 edits, 4 resource reads"
    detail_lines: list[str]   # deduped targets, shown only when len > 1
    calls: list[CallRecord]
    observations: list[CallRecord]
    has_error: bool
    duration_ms: float
```

Grouping key insight for SHIPIT: Cloudflare breaks runs on *prose*. SHIPIT's equivalent signal is a `text_delta` (or an assistant message with content) between tool batches. Fall back to `iteration` boundaries when the adapter doesn't stream.

`lowerFirst` on every label part after the first. Non-negotiable — it's the difference between a sentence and a list.

#### 4.1.3 `narrate/renderer.py` — the live terminal renderer

**The one real design decision in stage 1.** Cloudflare's UI re-renders freely because React holds state. A terminal cannot un-print. Two options:

| | Buffer until group closes | ANSI cursor-up rewrite |
|---|---|---|
| Live "Reading app.py…" | ✗ appears only when done | ✓ true in-place update |
| Piped / CI output | ✓ identical | ✗ needs a separate path |
| Complexity | low | high (wrapping, resize, scrollback) |

**Decision: both, selected by TTY.** A `LiveRegion` abstraction that on a TTY rewrites the last *k* lines in place (present tense, spinner), and off a TTY buffers and emits the final past-tense row only. `cli/ui.py` already handles `NO_COLOR`/`FORCE_COLOR`/encoding, so the fallback path is cheap. This mirrors the existing `style="auto"` split in `StreamRenderer` (`activity.py:122`).

Target rendering, matching §1.1:

```
  ⌕  3 resource reads                                        ›
     Enterprise Accounts · Open Tickets · Usage by Account

  Let me look at usage trends, open tickets and renewal dates together.

  ❯_ Ran code const risk = scoreAccounts(usa…                ›

  Three I would put on your list:
    • Northwind: usage down 38% since March, renews in six weeks.

                                        18,240 tokens · $0.12
```

Rules: gutter icon dim; label default weight; detail line dim monospace, dot-joined, only when >1; `›` dim, always; prose full weight, no gutter; footer right-aligned dim monospace.

**Additive only.** New `NarratorRenderer` alongside `StreamRenderer`, selected via `style="modern"`. `format_activity` and `StreamRenderer` are public exports in `__init__.py` and consumed by `chat_cli.py`, `serve.py`, and `cli/commands/*`; `tests/test_activity_trace.py` and `test_tool_output_formatting.py` pin their current behavior. Do not rewrite them.

#### 4.1.4 Event vocabulary

Add to `models.py:EventType`, **in the same commit**: the two already-emitted-but-undeclared types `tool_denied` and `text_delta`, plus `usage_tick` (live cost) and `group_closed`. The Literal is already drifting; adding to it without fixing the drift compounds the problem.

#### 4.1.5 The HUD

`CostTracker.calculate_cost()` is callable mid-run with cumulative usage from `runtime._total_usage`. Emit `usage_tick` after each `_track_usage` call; the renderer keeps a right-aligned footer. Format: `f"{tokens:,} tokens · ${cost:.2f}"` — thousands separators, matching §2.10.

#### Acceptance criteria

- `summarize("bash", {"command": "pytest -q\n"})` → `Ran pytest -q`
- `summarize("open_url", {"url": "https://github.com/x/y?z=1"})` → `Fetched github.com`
- Three `read_file` + two `edit_file` in one batch → one row, `Read 3 files, made 2 edits`
- An unknown MCP tool `linear__create_issue` → `Created issue`, never a crash
- Piped to a file: no ANSI, no cursor codes, identical content
- Existing `StreamRenderer` tests unchanged and passing

### Stage 2 — Tool contracts + deferred approvals ✅ LANDED

`shipit_agent/tools/contracts.py` + `shipit_agent/approvals/` + 80 tests.
**2,238 tests pass, 0 failures.**

```
  ⌕ Read 2 files ›
    guests.csv · venue.md

42 guests replied Yes. I'll send the venue change notice.

  ● Used Slack #events
    #1 · comms.send
    Always approve   Deny   Approve

Queued the notice — approve it when you're ready.

                                             46,410 tokens · claude-opus-5
```

The agent **finished the run**. Nothing was sent. `queue.approve_all(by="rahul")`
sent it afterwards.

**Tool contracts first, because the UI is downstream of the declaration.**
Before this, exactly **1 of 50** tools declared `read_only`; everything else was
inferred from name globs in `permissions.py`, which silently mis-classifies
anything called `figma` or `linear__create_issue`. Now all 50 declare a
`ToolContract`: `read_only`, `action_kind {tag, label}`, `implements_revert`,
`await_decision`, `auto_approvable`, `destructive`. Resolution order is tool
declaration → registration → table → heuristics, so the globs are a last resort
rather than the answer. `register_contract()` covers MCP and custom tools.

Two invariants fail loudly at construction: `auto_approvable` requires an
`action_kind` (rules key on the tag, so untagged can never match one), and a
`destructive` action can never be `auto_approvable`.

**The `await_decision` split is the honest part.** Cloudflare can *simulate* a
pending action because each Gatekeeper owns the remote resource. Our 50 tools
are unrelated functions — a simulated `bash` output would be a lie the model
then reasons over. So:

- A call whose **result the agent reasons over** (`bash`, `sql`, `run_code`)
  declares `await_decision` and still blocks.
- A call whose **effect is elsewhere** (`slack`, `jira`, `notion`) is queued,
  and the model is told the truth: *"queued for approval — it has NOT run yet.
  Assume it will succeed and continue. Do not retry it and do not read back its
  effects."* Never a fabricated result.

**`AutoApprovalDrainer` is ported exactly**, including the four properties that
make it safe: in-id-order application stopping at the first manual gate (never
reaching past it); both signals required (contract verdict **and** an enabled
rule); single-flight with a rerun flag; and attribution to the person who
enabled the rule, not the agent. Tested under 8 concurrent drainers over 20
actions — each applied exactly once.

**One gate, both runtimes.** The decision lives in `approvals/gate.py` and both
`runtime.py` and `async_runtime.py` call it, because every past divergence
between those two files has been a bug.

**Three bugs this shook out:**

1. `ActionKind` collided with the already-public `computer_use.ActionKind` at
   the package root — the new import shadowed it. Aliased to `ToolActionKind`.
2. A deferred call never emits `tool_called` (the gate returns first), so prose
   announcing the action never flushed and ran into the next sentence.
3. `comms.send` was not `auto_approvable`, making "Always approve" unreachable
   for the exact case the reference screenshot shows it on.

**Prerequisite:** stage 1 landed.

**The honest constraint, stated up front.** Cloudflare can *simulate* pending actions because each Gatekeeper owns the remote resource and can model its state. SHIPIT's 50 tools are unrelated Python functions — `bash`, `sql`, and `write_file` cannot be simulated. Porting simulation wholesale would mean **fabricating tool results**, which is worse than blocking.

**The portable subset:**

- `ActionQueue` with `ActionDescription` (title, markdown description, `implements_revert`, `auto_approvable`, `action_kind: {tag, label}`, `await_decision`).
- A queued action returns to the model: `"[queued for approval — assume it succeeded and continue; do not retry]"`. Truthful. The model keeps working; dependent *reads* may be stale, and that is stated rather than hidden.
- `await_decision=True` (the default for `bash`, `sql`, anything unreversible) suspends the turn — the current blocking behavior, but now opt-in per action kind rather than universal.
- `AutoApprovalDrainer` ported **exactly**, including in-order drain, stop-at-first-manual-gate, both-signals eligibility, single-flight with rerun flag, and attribution to the rule-enabler.
- Inline approval rendering per §1.2, with `Always approve · Deny · Approve`; pending descriptions never collapsed.

**Both runtimes.** `runtime.py` and `async_runtime.py` are parallel implementations (`async_runtime.py` already shares `authorize_tool` but lacks healing, nudge-on-stall, and compaction). Stage 2 must land in both or they diverge permanently. Consider extracting the shared gate into a `_ToolGate` mixin as part of this work.

### Stage 3 — Streaming input, checkpoint compaction, `give_up` ✅ LANDED

`narrate/json_stream.py`, `compaction.py`, `tools/give_up/` + 151 tests.
**2,392 tests pass, 0 failures.**

**`StreamingToolInputParser`** — a faithful port of Cloudflare's incremental
JSON reader. Decodes one designated string field (`content`, `code`, `command`)
as the model writes it, so a file can type itself out instead of appearing all
at once. Same 11-state machine, same O(n) single-pass scan, same
`prefix_fields` contract (fields before the streamed one are `json.loads`-ed in
one shot at the moment they're known complete). Chunk-boundary safety is tested
at **every single split point** of a payload, char-by-char against `json.loads`,
including `\u00e9` escapes split at all six offsets.

**Checkpoint compaction** replaces the naive path. Four changes:

| | before | now |
|---|---|---|
| budget | `len//4`, flat 0.75 | per-model window table, 0.85 trigger / 0.30 retain |
| cut point | "last 4 messages" | turn boundary, with a step-boundary fallback |
| prompt | "summarize this" | six-heading handoff + injection defense |
| history | destructively replaced | preserved; only the replay window moves |

The injection clause matters: the transcript being summarized is untrusted
input, and the compaction call is the one request in a run with no tools and no
guardrails. It is told explicitly that the transcript is data, not instructions.

**`give_up`** — a real tool with a required reason, surfaced as
`result.metadata["gave_up"]` / `["give_up_reason"]` / `["give_up_needs"]`. An
empty reason is *refused* rather than recorded, since a stop with no reason is
worse than no stop. Replaces guessing at prose.

**Four bugs shaken out:**

1. `get_model_limits` split on `.` to strip vendor prefixes, turning
   `gemini-2.5-pro` into `5-pro` and losing the match. Now it tries the id
   as given first, then peels routing prefixes one segment at a time.
2. An explicit `context_window_tokens` had a default 8k output reservation
   subtracted from it, so `context_window_tokens=100` produced a budget of 1.
   A caller-supplied budget is now taken as the budget.
3. **Turn-boundary-only cutting could not compact a single long turn** — one
   prompt, thirty tool calls, no turn boundary anywhere. That is precisely the
   shape that most needs compacting. Added a step-boundary fallback (cut before
   an assistant message), which still never orphans a tool result.
4. A trailing-garbage test asserted the parser validates the whole object; it
   deliberately stops once the streamed field closes. Documented rather than
   "fixed".

**Original scope:**

- **`narrate/json_stream.py`** — port `StreamingToolInputParser` to Python. Same 11-state machine, same `prefix_fields` / `streaming_value` contract. Consumers: `write_file`/`edit_file` (`content`/`replacement`) and `run_code`/`bash` (`code`/`command`). Requires an LLM adapter that surfaces partial tool-call arguments; `anthropic_adapter` and `openai_adapter` both can, `litellm_adapter` needs checking. **Terminal rendering:** a live diff region rather than a CRDT — same effect, far less machinery.
- **Checkpoint compaction** — replace `_compact_messages`/`_summarize_for_compaction`. Needs (a) a real per-model token table — extend `costs/pricing.py`, which already keys by model; (b) turn-start boundary detection; (c) the six-heading handoff prompt **including the ignore-instructions-in-transcript clause**; (d) immutable checkpoints so history survives.
- **`give_up` tool** — required `reason` string; sets `metadata["gave_up"]`. Then delete the `_INTENT_MARKERS` heuristic (`runtime.py:97-108`), or demote it to a fallback for models that won't call the tool.

### Stage 4 — Code mode (the 50→14 collapse)

The biggest win and the biggest risk. Ship stages 1–3 first.

- `execute_code` tool running Python in the existing `code_execution` sandbox, with connectors exposed as an `env` namespace instead of as tools.
- `describe_binding(name)` returning the type signature for **one** connector.
- `ResourceCatalog` per connector — bounded, sorted, re-validated host-side (untrusted connector output), folded into the system prompt.
- Keep the 50 tools available behind a flag; this is opt-in per agent (`Agent(code_mode=True)`), not a migration.

Expected effect: prompt tool-schema block from thousands of tokens to a few hundred; cross-connector composition in one call.

### Stage 5 — Surfaces

- `chat_cli.py` (1375 lines) adopts `NarratorRenderer`.
- `serve.py` SSE emits the new event types so a web client can render identically.
- A `--share` flag rendering a run as a standalone HTML transcript — the screenshots' look, in the browser.

---

## 5. Non-goals

Explicitly **not** porting, and why:

| Not porting | Why |
|---|---|
| Gadgets / Dynamic Workers / Durable Objects | Cloudflare-runtime-specific; SHIPIT is a library, not a platform |
| Cap'n Web RPC | solves a browser↔worker problem SHIPIT doesn't have |
| Y.Doc CRDT file previews | multiplayer machinery for a single-user terminal; a live diff gets 90% of the effect |
| Multiplayer presence | no shared workspace concept |
| Blueprints / app sandboxing | a different product |
| **Simulated action results** | not truthfully implementable over 50 unrelated tools (§4 stage 2) |

---

## 6. Risks

1. **`EventType` drift.** Already broken; every stage adds events. Fix the Literal in stage 1 or it silently rots.
2. **Two runtimes.** `runtime.py` / `async_runtime.py` divergence is a standing hazard that stage 2 makes acute.
3. **Terminal in-place rendering** is genuinely fiddly — line wrapping, resize, scrollback. The TTY/non-TTY split contains the blast radius.
4. **Public API stability.** `StreamRenderer` and `format_activity` are exported and load-bearing. Additive only.
5. **Adapter capability variance.** Stage 3's streaming input needs partial tool-call arguments from the provider. Sniff per-adapter the way `accepts_text_delta_callback` already does; degrade to non-streaming, never crash.

---

## 7. First commit

```
shipit_agent/narrate/__init__.py       new — exports
shipit_agent/narrate/verbs.py          ✅ drafted
shipit_agent/narrate/grouping.py       new — work-run engine
shipit_agent/narrate/renderer.py       new — NarratorRenderer + LiveRegion
shipit_agent/models.py                 + 4 EventTypes (2 are existing bugs)
shipit_agent/runtime.py                + usage_tick emit (1 line, no semantics)
shipit_agent/__init__.py               + exports
tests/test_narrate_verbs.py            new
tests/test_narrate_grouping.py         new
tests/test_narrate_renderer.py         new — incl. piped-output golden file
```

Nothing else. Stage 1 does not touch the loop.
