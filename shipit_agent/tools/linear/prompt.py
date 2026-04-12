from __future__ import annotations

LINEAR_PROMPT = """

## linear
Search Linear issues and create work items using a connected Linear workspace.

**When to use:**
- The user asks about tickets, issues, project status, or sprint progress in Linear
- Looking up specific issues by ID, title, or assignee
- Creating new issues or tasks as part of a workflow
- Searching the backlog for related work or duplicate issues

**Rules:**
- Use configured connector credentials — do not ask for tokens in chat
- Use focused queries: filter by project, team, status, assignee, or label
- When creating issues, confirm title and description with the user via `request_human_review` first
- Return issue ID, title, status, and assignee in results
""".strip()
