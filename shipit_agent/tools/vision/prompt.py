from __future__ import annotations

VISION_PROMPT = """
## vision
Send an image to a vision-capable LLM and get back a textual analysis.

**When to use:**
- A screenshot was just captured (e.g. via ``computer_use``) and you need to
  reason about what's on screen — buttons, fields, error dialogs, layout.
- The user pasted a diagram, UI mock, whiteboard photo, architecture sketch,
  or chart and wants it described, critiqued, or turned into code.
- You need OCR-like extraction from a design mock, PDF page image, receipt,
  error screenshot, or log capture.
- Comparing two screenshots (before/after) — call the tool twice and
  describe both, then reason over the two descriptions.

**How to use:**
- ``image`` can be any of:
  - filesystem path: ``./screenshot.png`` or ``/tmp/shot.jpg``
  - URL: ``https://example.com/foo.png``
  - data URL: ``data:image/png;base64,iVBOR...``
  - raw base64 (auto-wrapped as a PNG data URL)
- ``prompt`` is the question you want answered about the image
  (e.g. "Is there a Login button visible? If so, where?"). If omitted it
  defaults to a generic "describe this image in detail".
- ``detail`` is ``low`` | ``high`` | ``auto`` — use ``high`` for OCR /
  dense UI / small text; ``low`` for quick layout descriptions.

**Rules:**
- Pair with ``computer_use`` for the capture -> analyse loop.
- One image per call. For multi-image reasoning, call the tool per image
  and reason over the summaries.
- If the image isn't reachable (missing file, bad URL), the tool returns
  an ``image_not_found`` error and you should surface that to the user
  instead of guessing.
""".strip()
