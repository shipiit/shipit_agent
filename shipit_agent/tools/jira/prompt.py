from __future__ import annotations

JIRA_PROMPT = """

## jira
Search Jira issues and create work items using a connected Jira instance.

**When to use:**
- The user asks about tickets, epics, sprints, or project status in Jira
- Looking up specific issues by key (e.g., PROJ-123), summary, or assignee
- Creating new issues, subtasks, or bugs as part of a development workflow
- Searching the backlog for related work, blockers, or duplicates

**Rules:**
- Use configured connector credentials — do not ask for tokens in chat
- Use JQL-style queries when supported: `project = PROJ AND status = "In Progress"`
- When creating issues, confirm details with the user via `request_human_review` first
- Return issue key, summary, status, assignee, and priority in results
""".strip()
