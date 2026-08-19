"""Guidance the model sees alongside the fetch_url tool."""

DESCRIPTION = (
    "Fetch a URL and return its readable text. Use this rather than recalling "
    "what a page says — a page's current content is the only thing worth quoting."
)

INSTRUCTIONS = "Fetch a page before describing its contents. If a fetch fails, say so rather than answering from memory."
