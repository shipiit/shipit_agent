---
title: Multimodal Chat (inline media references)
description: Users paste [url] or ![alt](url) anywhere in their prompt — the agent extracts the media, builds a multimodal content message, and the vision LLM sees the image right where the user mentioned it. Works with Anthropic, OpenAI, Bedrock, Gemini through one API.
---

# Multimodal Chat

> Users write `"Hey what is this [https://example.com/cat.png] about?"` and the
> agent automatically converts that into a real multimodal message — image
> content block at the exact position the user mentioned it, surrounding
> text preserved on either side.

The trick is **interleaving**. When a user writes:

```
"Compare [https://x.com/a.png] vs [https://y.com/b.png]. Which is better?"
```

the model gets:

```
[text: "Compare "]
[image: a.png]
[text: " vs "]
[image: b.png]
[text: ". Which is better?"]
```

Order preserved. That's what makes the model understand spatial intent.

---

## Three syntaxes

| Syntax | Example | Use when |
| --- | --- | --- |
| **Bracket URL** | `[https://example.com/img.png]` | Quick paste, no caption |
| **Markdown** | `![alt text](https://example.com/img.png)` | You want to label the image |
| **Media UUID** | `[media:abc123]` | Reference a previously-uploaded asset by ID |

All three work in the **middle, start, or end** of any sentence. Mix and match
freely:

```
Hey, look at this ![first sketch](https://acme.com/s1.png) and compare it to
[https://acme.com/s2.png]. Then explain how it differs from [media:reference-42].
```

---

## Quick start

```python
from shipit_agent import Agent, MediaParser

parser = MediaParser(
    allowlist_domains=["*"],          # production: lock to your CDN
    max_size_mb=10,
)

agent = Agent(llm=vision_llm, media_parser=parser)

result = agent.run(
    "What do you see in [https://example.com/cat.png]? Explain in detail."
)
print(result.output)
# → "I see a tabby cat sitting on a windowsill, looking out at..."
```

That's it. The `MediaParser` extracts the URL, decides it's an image (from
the `.png` extension), builds an Anthropic-shape content-block message,
and the runtime hands it straight to the vision LLM.

---

## How extraction works (under the hood)

```python
from shipit_agent import MediaParser, build_multimodal_message

parser = MediaParser()
parsed = parser.parse(
    "Hey what is this [https://x.com/photo.png] about?"
)

print(parsed.segments)
# [TextSegment("Hey what is this "),
#  MediaSegment(MediaReference(url="https://x.com/photo.png", kind=IMAGE)),
#  TextSegment(" about?")]

message = build_multimodal_message(parsed, role="user")
# {
#   "role": "user",
#   "content": [
#     {"type": "text", "text": "Hey what is this "},
#     {"type": "image", "source": {"type": "url", "url": "https://x.com/photo.png"}},
#     {"type": "text", "text": " about?"},
#   ]
# }
```

That JSON is what the vision LLM sees. Anthropic, OpenAI, Bedrock, and
Gemini all accept either this exact shape (Anthropic native) or a
provider-specific shape that LiteLLM normalises automatically.

---

## Domain allowlist + denylist

```python
parser = MediaParser(
    allowlist_domains=["*.s3.amazonaws.com", "github.com", "*.acme.internal"],
    denylist_domains=["evil.com"],
    max_size_mb=10,
)
```

* **Allowlist** is glob-matched against the URL host (default: `["*"]`).
  Anything not on the allowlist is **silently kept as text** — the user
  sees the bracket-URL syntax in the conversation but the model doesn't
  fetch it.
* **Denylist** is checked AFTER the allowlist match — wins on conflict.
* **`max_size_mb`** is enforced via a HEAD request when configured (off by
  default to keep parsing pure).

When a reference fails validation, the raw token is preserved inline as
plain text so the user sees what was blocked rather than getting a silent
drop.

---

## Local uploads via `[media:<uuid>]`

For uploaded files (avatars, screenshots, PDFs the user dropped in), use
the UUID syntax with a `MediaStore`:

```python
from shipit_agent import (
    Agent, MediaParser,
    InMemoryMediaStore, FileMediaStore, StoredMedia,
)

store = FileMediaStore(".shipit_media.json")
store.put(StoredMedia(
    id="user-screenshot-42",
    url="https://your-cdn.com/uploads/abc.png",
    mime="image/png",
    alt="Dashboard screenshot user uploaded",
))

parser = MediaParser(media_store=store)
agent = Agent(llm=vision_llm, media_parser=parser)

agent.run("What's broken in [media:user-screenshot-42]? Suggest a fix.")
```

The store can be backed by anything — S3, your database, a local JSON
file. Implement the four-method `MediaStore` Protocol and you're done.

---

## Media kinds

The parser detects four kinds from URL extension or store-provided MIME:

| Kind | Detected from | Block emitted |
| --- | --- | --- |
| `IMAGE` | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.svg` · `image/*` | `{type: "image", source: {url}}` |
| `AUDIO` | `.mp3` `.wav` `.m4a` `.ogg` `.flac` · `audio/*` | `{type: "audio", source: {url}}` |
| `VIDEO` | `.mp4` `.mov` `.webm` `.avi` `.mkv` · `video/*` | `{type: "video", source: {url}}` |
| `DOCUMENT` | `.pdf` `.doc` `.docx` `.txt` `.md` · `application/pdf` | `{type: "document", source: {url}}` |

Unknown kinds fall back via the `fallback=` setting on
`build_multimodal_message`:

| `fallback` | Behavior |
| --- | --- |
| `"markdown"` (default) | Drop URL into text run as `![alt](url)` so the model still sees the link |
| `"drop"` | Silently skip the reference |
| `"text"` | Replace with `<media: alt>` placeholder |

---

## Setting up images

Images are the easiest kind to wire up — every vision-capable LLM
supports them and the parser detects them automatically.

### Minimal setup

```python
from shipit_agent import Agent, MediaParser
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(model="claude-sonnet-5-5")
parser = MediaParser(allowlist_domains=["*.s3.amazonaws.com", "github.com"])
agent = Agent(llm=llm, media_parser=parser)

result = agent.run(
    "Describe the colors and composition of "
    "[https://github.com/openai/openai-cookbook/raw/main/images/cover.png]."
)
print(result.output)
```

### Side-by-side comparison

```python
agent.run(
    "Compare these two homepages and tell me which conveys more "
    "trust:\n\n"
    "Variant A: ![v1](https://acme.com/v1.png)\n"
    "Variant B: ![v2](https://acme.com/v2.png)"
)
```

The vision LLM sees both renders interleaved with the question and
returns a specific critique — copy contrast, hierarchy, whitespace.

### Annotating user-uploaded screenshots

```python
from shipit_agent import InMemoryMediaStore, StoredMedia

store = InMemoryMediaStore()
asset_id = store.put(StoredMedia(
    id="",                              # auto-generated
    url="https://your-cdn.com/uploads/abc.png",
    mime="image/png",
    alt="User dashboard at 9:13 AM",
))

parser = MediaParser(allowlist_domains=["*"], media_store=store)
agent = Agent(llm=llm, media_parser=parser)

agent.run(f"Why is the chart blank in [media:{asset_id}]?")
```

### Multi-image batch in one prompt

```python
urls = [f"https://acme.com/frame-{i:03d}.png" for i in range(8)]
prompt = "Tag each of these animation frames:\n" + "\n".join(
    f"Frame {i}: [{u}]" for i, u in enumerate(urls)
)
result = agent.run(prompt)
```

Each `[url]` becomes its own image block — the LLM sees all eight in
order. (Anthropic caps the total payload around ~20 MB; the parser's
`max_size_mb=` setting is your guard rail.)

---

## Setting up audio

Audio is the **killer feature for voice notes, meeting clips, and
interview transcripts** — modern vision LLMs hear the actual bytes
instead of going through a separate Whisper step. That means tone,
pacing, multiple speakers, and hesitation come through.

### Provider support at a glance

| Provider | Audio formats | Notes |
| --- | --- | --- |
| Anthropic Claude (Sonnet 4.5+) | `.mp3` `.wav` `.m4a` `.ogg` `.flac` | Native audio blocks |
| OpenAI GPT-4o (audio preview) | `.mp3` `.wav` | LiteLLM normalises |
| AWS Bedrock Nova Pro / Lite | `.mp3` `.wav` `.flac` | Bedrock content blocks |
| Google Gemini 2.x | `.mp3` `.wav` `.aac` `.flac` `.ogg` | Native multipart |

### Minimal audio setup

```python
from shipit_agent import Agent, MediaParser
from shipit_agent.llms import GeminiChatLLM

llm = GeminiChatLLM(model="gemini-2.0-flash")
parser = MediaParser(allowlist_domains=["*.acme.com"])
agent = Agent(llm=llm, media_parser=parser)

result = agent.run(
    "Summarise the action items from "
    "[https://acme.com/standup.mp3]."
)
print(result.output)
```

The `.mp3` extension routes the URL into an `audio` content block.
The LLM reads the actual audio — no `whisper.transcribe()` in the
middle.

### Voice-note triage with attachments

```python
from shipit_agent import InMemoryMediaStore, StoredMedia

store = InMemoryMediaStore()
asset_id = store.put(StoredMedia(
    id="",
    url="https://uploads.acme.com/voice/abc.m4a",
    mime="audio/m4a",
    alt="Customer voicemail (12 sec)",
))

parser = MediaParser(allowlist_domains=["*"], media_store=store)
agent = Agent(llm=llm, media_parser=parser)

agent.run(
    f"Triage this voicemail: [media:{asset_id}]. "
    "Tag urgency (P0/P1/P2/P3) and pull out any concrete asks."
)
```

### Mixed audio + text reference

```python
agent.run(
    "Compare what was said in this kickoff "
    "[https://acme.com/kickoff.mp3] to the actual roadmap PDF "
    "[https://acme.com/roadmap.pdf]. Where do the two diverge?"
)
```

Audio and document blocks interleave with the question — the LLM
hears the kickoff, reads the PDF, and reports drift.

### When audio support is missing

Some smaller models can't ingest audio. The parser still emits a
content block; if the model rejects it, set `fallback="markdown"`
(default) on `build_multimodal_message` so the URL stays in the text
run as a normal link. For a text-only model, give the agent a transcription
tool of your own: a function that sends the audio to your speech-to-text
service, wrapped with `FunctionTool.from_callable`. The agent calls it,
then works from the transcript.

---

## Setting up video

Video is heavier than audio. Some providers ingest the whole clip
natively; others sample frames at fixed intervals. The parser handles
both cases the same way — you write one prompt and the runtime adapts.

### Provider support at a glance

| Provider | Strategy | Length cap | Notes |
| --- | --- | --- | --- |
| Google Gemini 2.x | Native video ingest, audio + frames | ~1 hour @ Gemini Pro, ~10 min @ Flash | Best video support today; reads narration + visuals |
| AWS Bedrock Nova Pro | Native video ingest | ~30 min | `.mp4` `.mov` `.webm` |
| OpenAI GPT-4o | Frame sampling (1–2 fps) | a few minutes | Treats as image batch internally |
| Anthropic Claude | Frame sampling preview | a few minutes | Best-effort; check beta docs |

### Minimal video setup

```python
from shipit_agent import Agent, MediaParser
from shipit_agent.llms import GeminiChatLLM

llm = GeminiChatLLM(model="gemini-2.0-pro")        # full video ingest
parser = MediaParser(allowlist_domains=["*.acme.com"])
agent = Agent(llm=llm, media_parser=parser)

result = agent.run(
    "Watch [https://files.acme.com/demo.mp4] and write release notes "
    "covering: (1) what the user does, (2) any flickers or jank, "
    "(3) accessibility issues."
)
print(result.output)
```

The `.mp4` extension routes the URL into a `video` content block.
Gemini reads both the visual frames AND the audio track in one shot —
so a screen-recording with voice-over gives you visuals + narration
together.

### Bug-report video triage

```python
from shipit_agent import InMemoryMediaStore, StoredMedia

store = InMemoryMediaStore()
clip_id = store.put(StoredMedia(
    id="",
    url="https://uploads.acme.com/bugs/screen-recording.mov",
    mime="video/quicktime",
    alt="User screen recording: checkout flow stuck on step 3",
))

parser = MediaParser(allowlist_domains=["*"], media_store=store)
agent = Agent(llm=llm, media_parser=parser)

agent.run(
    f"Watch this bug report: [media:{clip_id}]. "
    "Identify the precise step the user got stuck on, the UI element "
    "they last interacted with, and any console errors visible. "
    "Then write a reproducible bug ticket."
)
```

The agent watches the recording, sees the user's mouse path, the
broken button, the red toast — and emits a structured ticket with
timestamps.

### Long-form summarisation (chapter markers)

```python
agent.run(
    "Summarise [https://files.acme.com/all-hands.mp4] (40 min). "
    "Output: (1) one-paragraph TL;DR, (2) chapter markers as "
    "[mm:ss] timestamps with topic, (3) any commitments or asks "
    "made by leadership."
)
```

Gemini handles ~1 hour of video in one call. For longer content,
chunk the file or use the [Autopilot](../autopilot/index.md) feature
to stream chapter-by-chapter summaries.

### Mixed video + image — visual diff

```python
agent.run(
    "Compare the marketing video [https://acme.com/promo-v1.mp4] "
    "with the new key art ![v2](https://acme.com/key-art-v2.png). "
    "Does the still frame match the video's tone and palette?"
)
```

Visual consistency review across formats — video frames cross-checked
against a static asset, all in one prompt.

### Frame-by-frame analysis (when you need precision)

When pixel-level detail matters more than narration (animation review,
motion blur, artifacts), extract frames first with a tool of your own,
for example a function that runs `ffmpeg -vf fps=2` and returns the frame
paths, and pass the frames to a vision model as images.

### When video support is missing

Same pattern as audio — the parser still emits the block, and your
fallback handler can chain a separate extractor (Whisper for audio
track, ffmpeg for keyframes) and feed those back into the agent as
plain image/text blocks.

---

## Real-life patterns

### Pattern 1 — design review

```python
agent.run(
    "Compare these two button designs. Which is more accessible?\n\n"
    "Option A: ![old](https://figma.com/render/old.png)\n"
    "Option B: ![new](https://figma.com/render/new.png)"
)
```

The vision LLM sees both renders side-by-side with the question and
picks the more accessible one.

### Pattern 2 — bug triage from screenshot

```python
agent.run(
    "User uploaded this screenshot of a 500 error: [media:err-42]. "
    "What's the most likely cause? Check logs at [https://kibana.acme.com/error-42]."
)
```

Combines a stored screenshot (resolved via MediaStore) with an
allowlisted log URL.

### Pattern 3 — multi-page PDF analysis

```python
agent.run(
    "Read [https://x.com/Q3-earnings.pdf] and summarise the three biggest "
    "risks mentioned in the management commentary."
)
```

PDF extension → DOCUMENT block. Anthropic + Bedrock support PDF input
natively.

### Pattern 4 — chained vision + retrieval

```python
result = agent.run(
    "What's in this image [https://x.com/chart.png]? Then look up "
    "the underlying data via web_search and verify the numbers."
)
```

Multimodal blocks compose with regular tools — vision interprets the
chart, then web_search verifies.

### Pattern 5 — kitchen sink (image + audio + video + PDF in one prompt)

```python
agent.run(
    "Tag this asset folder. "
    "Image: [https://acme.com/cover.png]. "
    "Audio: [https://acme.com/voice.mp3]. "
    "Video: [https://acme.com/clip.mp4]. "
    "Doc:   [https://acme.com/spec.pdf]."
)
```

Each reference is routed to the right block type by extension. Source
order is preserved end-to-end.

### Pattern 6 — drift detection (audio + PDF)

```python
agent.run(
    "Compare what was said in this kickoff "
    "[https://acme.com/kickoff.mp3] to the actual roadmap PDF "
    "[https://acme.com/roadmap.pdf]. Where do the two diverge?"
)
```

The LLM hears the kickoff, reads the PDF, and reports drift between
the two — useful for compliance, retros, and standup → ticket sync.

---

## Persisting uploads — `FileMediaStore`

Across restarts you usually want a real backing store. `FileMediaStore`
ships for local development; for production implement the four-method
`MediaStore` Protocol against your S3 / DB / CDN.

```python
from shipit_agent import FileMediaStore, StoredMedia

store = FileMediaStore(".shipit_media.json")
uid = store.put(StoredMedia(
    id="",                                  # auto-generated UUID
    url="https://acme.com/avatar.png",
    mime="image/png",
    alt="User avatar",
))

# Later — different process — same uid resolves
store2 = FileMediaStore(".shipit_media.json")
loaded = store2.resolve(uid)
print(loaded.url, loaded.alt)
```

Custom backend example (S3 sketch):

```python
from typing import Iterator
from shipit_agent import StoredMedia

class S3MediaStore:
    def __init__(self, client, bucket: str):
        self._s3 = client
        self._bucket = bucket

    def resolve(self, media_id: str) -> StoredMedia | None:
        obj = self._s3.head_object(Bucket=self._bucket, Key=media_id)
        if obj is None:
            return None
        return StoredMedia(
            id=media_id,
            url=f"https://{self._bucket}.s3.amazonaws.com/{media_id}",
            mime=obj["ContentType"],
            alt=obj.get("Metadata", {}).get("alt", ""),
        )
    def put(self, media: StoredMedia) -> str: ...
    def list_all(self) -> Iterator[StoredMedia]: ...
    def delete(self, media_id: str) -> bool: ...
```

---

## One-shot reference extraction

When you only need the list (logging, audit trails, asset-pipeline
hooks) — skip segments and use the convenience function:

```python
from shipit_agent import extract_media_refs

refs = extract_media_refs(
    "See [https://acme.com/a.png] and ![b](https://acme.com/b.png).",
    allowlist_domains=["*.acme.com"],
)
for r in refs:
    print(r.kind.value, r.url, r.alt)
# image https://acme.com/a.png ''
# image https://acme.com/b.png 'b'
```

---

## Combining with other features

### + Verifier network
```python
from shipit_agent import VerifierNetwork

verifier = VerifierNetwork(
    llm=haiku_llm,
    goal="Look at images user provides; never download from non-allowlisted domains.",
)

agent = Agent(llm=opus_llm, media_parser=parser, verifier=verifier)
```

The verifier inspects the agent's tool calls — including any URL fetches
the agent might attempt as a follow-up.

### + Structured output
```python
from pydantic import BaseModel

class ImageAnalysis(BaseModel):
    subject: str
    colors: list[str]
    confidence: float

result = agent.run(
    "Analyze ![photo](https://x.com/p.png) and report findings.",
    output_schema=ImageAnalysis,
)
print(result.parsed)  # → ImageAnalysis(subject='cat', colors=[...], confidence=0.95)
```

### + Memory consolidation
After a few multimodal turns, the consolidator can remember "user often
asks about UI mockups; always emphasize accessibility critique" — that
preference promotes to core memory and shapes future runs.

---

## Tuning

```python
MediaParser(
    allowlist_domains=["*"],          # glob patterns
    denylist_domains=[],
    max_size_mb=None,                 # None = no size check
    media_store=None,                 # for [media:uuid] syntax
)
```

| Knob | Lower | Higher |
| --- | --- | --- |
| `allowlist_domains` (narrow) | More security, less friction for trusted CDNs | More flexibility, more risk |
| `max_size_mb` | Cheaper API calls, may reject legit images | Higher fidelity |

**Production defaults:** lock allowlist to your CDN(s), set `max_size_mb=20`,
back the `MediaStore` with your real upload backend.

---

## Provider compatibility

| Provider | Image | Audio | Video | Document | Notes |
| --- | --- | --- | --- | --- | --- |
| Anthropic Claude | ✅ | preview | preview | ✅ PDF | Native content blocks |
| OpenAI GPT-4o / o-series | ✅ | ✅ | preview | preview | LiteLLM normalises |
| AWS Bedrock | ✅ Claude / Nova | ✅ Nova | ✅ Nova | ✅ Claude PDF | Via Bedrock content blocks |
| Google Gemini | ✅ | ✅ | ✅ | ✅ | Native multipart |

If your model can't read a kind, the fallback path keeps the URL in text so
it's never silently dropped.

---

## API reference

### `MediaParser`
```text
MediaParser(
    *,
    allowlist_domains: list[str] = ["*"],
    denylist_domains: list[str] = [],
    max_size_mb: float | None = None,
    media_store: MediaStore | None = None,
)
```

| Method | Returns | Notes |
| --- | --- | --- |
| `.parse(prompt)` | `ParsedPrompt` | Extract segments — text + media interleaved |
| `.is_allowed_domain(url)` | `bool` | Public for re-using the rules elsewhere |

### `ParsedPrompt`
| Property / Method | Notes |
| --- | --- |
| `.segments` | Ordered list of `TextSegment` / `MediaSegment` |
| `.media_refs` | Just the `MediaReference` items, in order |
| `.text` | Reconstruct as text, media → markdown placeholders |
| `.text_only` | Drop media entirely; keep surrounding text |
| `.has_media` | `True` if any media segment present |

### `build_multimodal_message(parsed, *, role="user", fallback="markdown")`
Returns `{"role": role, "content": [...]}` Anthropic-shape blocks.

### `MediaStore` (Protocol)
| Method | Notes |
| --- | --- |
| `resolve(media_id)` | `StoredMedia | None` |
| `put(media)` | Insert / overwrite |
| `list_all()` | All stored items |
| `delete(media_id)` | `bool` |

Implementations: `InMemoryMediaStore`, `FileMediaStore`, or your own.

### `extract_media_refs(prompt, *, allowlist_domains=None, media_store=None)`
Convenience: parse + return only the media refs.

---

## Going deeper

* [Notebook 60 — Multimodal chat](https://github.com/shipiit/shipit_agent/blob/main/notebooks/60_multimodal_chat.ipynb) — end-to-end examples
* [Verifier network](./verifier.md) — gate URL fetches that exfiltrate data
* [Structured output](../guides/structured-output.md) — typed analysis results from images
* [ComputerUseAgent](./computer-use.md) — the agent generates images for you
