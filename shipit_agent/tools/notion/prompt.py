from __future__ import annotations

NOTION_PROMPT = """

## notion
Search Notion pages and create content using a connected Notion workspace.

**When to use:**
- The user asks about internal documentation, notes, or knowledge base content in Notion
- Searching for meeting notes, project docs, design specs, or reference pages
- Creating new pages for documentation, notes, or structured content
- Finding information that was previously documented in the team's Notion workspace

**Rules:**
- Use configured connector credentials — do not ask for tokens in chat
- Use targeted search terms — Notion search works best with specific titles or keywords
- When creating pages, confirm content with the user via `request_human_review` first
- Return page titles, links, and relevant excerpts in results
""".strip()
