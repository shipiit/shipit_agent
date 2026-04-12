from __future__ import annotations

GOOGLE_CALENDAR_PROMPT = """

## google_calendar
Search and inspect Google Calendar events using a connected Google account.

**When to use:**
- The user asks about upcoming meetings, schedule availability, or event details
- Date-based lookups: "what's on my calendar today", "meetings this week"
- Finding specific events by title, attendee, or time range
- Checking for scheduling conflicts before proposing a meeting time

**Rules:**
- Use configured connector credentials — do not ask for OAuth tokens in chat
- Return event titles, times, and attendees in a clear, scannable format
- Respect time zones — include the timezone in results when relevant
- For creating events, confirm details with the user via `request_human_review` first
""".strip()
