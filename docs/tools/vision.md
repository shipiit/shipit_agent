---
title: vision
description: Send an image (file path, URL, data URL, or raw base64) to a vision-capable LLM and return a textual analysis. Pairs with computer_use for the capture → analyse loop.
---

# `vision`

Hand any image to a vision-capable LLM adapter (Claude, GPT-4o,
Gemini, Bedrock Claude, LiteLLM in OpenAI-compatible mode) and get
structured text back. Input can be a filesystem path, an `http(s)`
URL, a `data:image/...;base64,...` data URL, or raw base64 — the
tool normalises all four into the OpenAI-compatible `image_url` parts
format expected by vision adapters.

> **TL;DR** —
> `VisionTool(llm=my_vision_llm).run(ctx, image="./shot.png", prompt="Is there a Login button?")`
> returns an `output.text` with the analysis plus `metadata.usage` /
> `metadata.model` for cost tracking.

## When to use

- **Design reviewer** critiquing a UI mock, Figma export, or
  whiteboard photo.
- **Computer-use loop** — a screenshot was just captured by
  [`computer_use`](computer-use.md) and the agent needs to reason
  about buttons, fields, error dialogs, or layout.
- **OCR-like extraction** from receipts, error screenshots, dense
  UI shots, or a PDF page rendered as an image — set
  `detail="high"`.
- **Before / after** comparisons — call the tool twice and reason
  over the two textual summaries (one image per call).

## Quick example

```python
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.vision import VisionTool
from shipit_agent.llms import OpenAIChatLLM

vision = VisionTool(llm=OpenAIChatLLM(model="gpt-4o-mini"))
ctx = ToolContext(prompt="demo")

out = vision.run(
    ctx,
    image="./screenshot.png",
    prompt="Is there a Login button visible? If so, where on the page?",
    detail="high",
    max_tokens=512,
)
print(out.text)
```

## Setup

`VisionTool` is **not** a connector — there is no `CredentialRecord`.
It needs a vision-capable LLM adapter, supplied one of two ways:

```python
# Option 1 — explicit at construction time
vision = VisionTool(llm=OpenAIChatLLM(model="gpt-4o"))

# Option 2 — share the agent's LLM via context state
ctx = ToolContext(prompt="demo", state={"llm": my_llm})
vision = VisionTool()
vision.run(ctx, image=...)
```

If no LLM is resolvable the tool returns `metadata.error = "no_llm"`
instead of raising.

## Parameters

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `image` | string (required) | — | Filesystem path, `http(s)://` URL, `data:image/...;base64,...` data URL, or raw base64 (≥ 16 chars). Paths are read from disk and wrapped into a PNG data URL when the suffix is unknown. |
| `prompt` | string | `"Describe this image in detail."` | The question asked of the image. |
| `detail` | `low` \| `high` \| `auto` | `auto` | `high` for OCR / dense UI / small text; `low` for a fast layout pass; `auto` lets the provider decide. |
| `max_tokens` | integer | `1024` | Upper bound on the vision response. |

## How image resolution works

```text
  "http(s)://..."          → passed through as a URL
  "data:image/...;base64," → passed through unchanged
  existing local path      → read, base64-encoded, wrapped as
                             data:<detected mime>;base64,<bytes>
  raw base64 (≥ 16 chars)  → wrapped as data:image/png;base64,<bytes>
  anything else            → image_not_found error
```

MIME inference uses the file suffix
(`.png`, `.jpg/.jpeg`, `.gif`, `.webp`) with `mimetypes` as a
fallback. Unknown suffixes default to `image/png`.

## As a tool handed to an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.tools.vision import VisionTool
from shipit_agent.tools.computer_use import ComputerUseTool

llm = OpenAIChatLLM(model="gpt-4o")
agent = Agent(
    llm=llm,
    tools=[ComputerUseTool(), VisionTool(llm=llm)],
    prompt=(
        "You are a desktop automation agent. Use computer_use to take "
        "a screenshot, then vision to describe what's on screen before "
        "deciding the next action."
    ),
)
agent.run("Is there a Login button on the current window? If yes, click it.")
```

## Output shape

```python
ToolOutput(
    text="<the LLM's analysis>",
    metadata={
        "provider": "vision",
        "model": "gpt-4o",             # from llm.model
        "usage": {...},                # whatever the adapter returns
        "detail": "high",
        "image_url": "data:image/png;base64,...",
    },
)
```

The underlying `Message` has `content` set to a human-readable
`"<prompt>\n\n[image_url: ...]"` string (so non-vision adapters
still see something useful) and stashes the structured parts list
on `metadata["parts"]` for vision-aware adapters to consume.

## Error shapes

| `error=` | Meaning | What to do |
| --- | --- | --- |
| `no_llm` | No LLM was resolvable from `VisionTool(llm=...)` or `context.state["llm"]` | Pass an LLM adapter. |
| `bad_input` | `image` was missing or not a string | Supply a string path / URL / data URL / base64. |
| `image_not_found` | Path-shaped string didn't exist, URL was malformed, or base64 failed the sanity check | Verify the file exists, or check the URL, or confirm the base64 string is ≥ 16 chars of the base64 alphabet. |

## Related

- [`computer_use`](computer-use.md) — the capture half of the
  capture → analyse loop.
- [Tool catalog](index.md) — every built-in tool.
- [Notebook 45 — cost router, async ask, vision, sandbox](https://github.com/shipiit/shipit_agent/blob/main/notebooks/45_cost_router_async_ask_vision_sandbox.ipynb)
  — worked `VisionTool` examples alongside the other v1.0.7 tools.
- [Specialists](../autopilot/specialists.md) — design-review /
  desktop-automation roles that benefit from vision.
