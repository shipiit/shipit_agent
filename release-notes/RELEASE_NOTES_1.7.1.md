# SHIPIT Agent 1.7.1 — attachments on `stream()`

A small follow-up to 1.7.0: media attachments now work on the streaming API,
not just the blocking one.

## Added

- **`agent.stream(prompt, images=[...], files=[...])`** — the streaming feed
  now accepts the same attachments as `agent.run()`:
  - **images** by URL, local path, or base64 (needs a vision-capable model);
  - **files** — text, markdown, and code inlined; PDFs as native document
    blocks where the provider reads PDF.

  ```python
  for event in agent.stream(
      "What is this image and both documents about?",
      images=["/path/to/screenshot.png"],
      files=["/path/to/spec.md", "/path/to/report.pdf"],
  ):
      if event.type == "text_delta":
          print(event.payload["chunk"], end="", flush=True)
  ```

Attachment paths may be anywhere on disk (unlike `read_file`, which is
confined to the project root). PDF handling is provider-specific: Anthropic
reads the document block natively; on OpenAI-compatible providers the PDF
degrades to a text placeholder, so extract text first with the `pdf` tool.

See the [changelog](../CHANGELOG.md).
