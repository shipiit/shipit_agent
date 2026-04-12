from __future__ import annotations

CUSTOM_API_PROMPT = """

## custom_api
Call a configured internal or third-party HTTP API using stored credentials and base URL metadata.

**When to use:**
- The user needs data from a custom internal system that does not have a dedicated tool
- Calling REST APIs for CRM, ERP, monitoring, or internal microservices
- Fetching or posting data to systems configured by the user or admin

**Rules:**
- Use the stored connector credentials and base URL — do not ask for raw API keys in chat
- Prefer dedicated tools (Gmail, Slack, Jira, etc.) when they exist for the target system
- Validate response status codes and handle errors clearly
- For destructive operations (POST, PUT, DELETE), confirm with the user via `request_human_review` first
- Return structured results — parse JSON responses rather than dumping raw output
""".strip()
