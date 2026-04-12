from __future__ import annotations

CONFLUENCE_PROMPT = """

## confluence
Search and create Confluence pages using a connected Confluence instance.

**When to use:**
- The user asks about wiki pages, runbooks, architecture docs, or team knowledge in Confluence
- Searching for existing documentation before writing something from scratch
- Publishing new documentation, post-mortems, or decision records to the team wiki
- Looking up how-to guides, onboarding docs, or operational procedures

**Rules:**
- Use configured connector credentials — do not ask for tokens in chat
- Search by space and title keywords for best results
- When creating or updating pages, confirm content with the user via `request_human_review` first
- Return page titles, space names, and links in results
""".strip()
