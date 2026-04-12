from __future__ import annotations

EDIT_FILE_PROMPT = """

## edit_file
Apply an exact text replacement patch to an existing file. Safer and more precise than a full rewrite.

**When to use:**
- Make a targeted edit without rewriting the whole file
- Replace a known block of code, text, or config
- Rename or update repeated text across the file with `replace_all`
- Fix bugs, update values, or refactor specific sections

**Decision tree:**
1. Need to change a few lines? → `read_file` then `edit_file` — best choice
2. Need to rename a variable everywhere? → `edit_file` with `replace_all=true`
3. Rewriting 80%+ of the file? → `read_file` then `write_file` instead
4. File does not exist yet? → use `write_file` instead

**Rules:**
- **Read the file first** with `read_file` — edits on unread files are rejected
- `old_text` must match the current file contents **exactly** (whitespace, indentation, newlines)
- Use the smallest uniquely identifying block that is still stable across minor changes
- When `old_text` appears multiple times and you want all replaced, set `replace_all=true`
- When `old_text` appears multiple times and you want only one, include more surrounding context to make it unique
- Prefer this tool over `write_file` for surgical edits — it is faster, safer, and preserves the rest of the file

**Workflow:**
```
glob_files → find the file
read_file  → see current contents
edit_file  → apply the patch
read_file  → verify the result (optional but recommended for critical edits)
```

**Anti-patterns:**
- Editing without reading first (will be rejected by the runtime)
- Using a huge `old_text` block when a smaller unique snippet works
- Forgetting exact whitespace — copy from the `read_file` output, do not retype
- Using `write_file` for a one-line change (unnecessary risk)
""".strip()
