from __future__ import annotations

GMAIL_PROMPT = """

## gmail_search
Search and read Gmail messages using a configured Google account.

**When to use:**
- The user asks about emails, inbox activity, senders, threads, or unread mail
- You need recent message context from Gmail instead of public web content

**Rules:**
- Use configured connector credentials rather than asking for raw tokens in chat
- Prefer focused Gmail queries such as `from:`, `subject:`, `label:`, or `is:unread`
- Return concise message previews and source links when available
""".strip()
