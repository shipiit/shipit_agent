from __future__ import annotations

SLACK_PROMPT = """

## slack
Search Slack content and post messages using a connected Slack workspace.

**When to use:**
- The user asks about Slack messages, channel activity, or conversation history
- Searching for discussions, decisions, or context shared in Slack channels
- Posting status updates, summaries, or notifications to a Slack channel
- Finding who said what about a topic in a specific channel or thread

**Rules:**
- Use configured connector credentials — do not ask for tokens in chat
- Prefer targeted channel + keyword searches over broad workspace-wide searches
- When posting messages, confirm content with the user via `request_human_review` first
- Return concise message previews with channel name, author, and timestamp
""".strip()
