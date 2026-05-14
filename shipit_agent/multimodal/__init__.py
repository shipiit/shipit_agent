"""Multimodal chat — inline media references in user prompts.

Users write things like::

    What do you see in [https://example.com/cat.png]?
    Compare ![sketch](https://acme.com/sketch.jpg) with [media:abc123].

The agent automatically:
1. Extracts every media reference from the user message,
2. Validates each (allowlisted domain, max size, supported MIME),
3. Builds a provider-agnostic multimodal user message —
   image / audio / video content blocks plus the cleaned text,
4. Hands the message to the LLM, which sees the media natively.

Three reference syntaxes, all interchangeable:

| Syntax                         | Use when |
| ------------------------------ | -------- |
| ``[https://...]``              | Quick paste of a URL |
| ``![alt text](https://...)``   | Markdown-image style with an alt label |
| ``[media:<uuid>]``             | Reference a previously-uploaded asset by ID (resolved via ``MediaStore``) |

Quick start::

    from shipit_agent import Agent
    from shipit_agent.multimodal import MediaParser

    parser = MediaParser(
        allowlist_domains=["*"],   # production: lock to your own CDN
        max_size_mb=10,
    )

    agent = Agent(llm=vision_llm, media_parser=parser)
    result = agent.run("What do you see in [https://example.com/cat.png]?")
    # → vision LLM gets an image block + the question, returns a description
"""

from __future__ import annotations

from .builder import build_multimodal_message
from .models import (
    MediaKind,
    MediaReference,
    MediaSegment,
    ParsedPrompt,
    Segment,
    TextSegment,
)
from .parser import MediaParser, extract_media_refs
from .store import (
    FileMediaStore,
    InMemoryMediaStore,
    MediaStore,
    StoredMedia,
)

__all__ = [
    "FileMediaStore",
    "InMemoryMediaStore",
    "MediaKind",
    "MediaParser",
    "MediaReference",
    "MediaSegment",
    "MediaStore",
    "ParsedPrompt",
    "Segment",
    "StoredMedia",
    "TextSegment",
    "build_multimodal_message",
    "extract_media_refs",
]
