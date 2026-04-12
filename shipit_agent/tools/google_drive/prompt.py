from __future__ import annotations

GOOGLE_DRIVE_PROMPT = """

## google_drive
Search and inspect Google Drive files using a connected Google account.

**When to use:**
- The user asks about documents, spreadsheets, or files stored in Google Drive
- Finding documents by name, type, folder, or recent modification
- Retrieving file metadata (owner, last modified, sharing status)
- Locating shared team documents, templates, or reference materials

**Rules:**
- Use configured connector credentials — do not ask for OAuth tokens in chat
- Return file names, types, and links in a clear format
- Use targeted search queries with file type filters when possible
- For large result sets, summarize and let the user narrow down
""".strip()
