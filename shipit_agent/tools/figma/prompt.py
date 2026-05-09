from __future__ import annotations

FIGMA_PROMPT = """

## figma
Read Figma files, render node images, browse comments, and introspect team/project/component
libraries on a connected Figma workspace (api.figma.com) via a Personal Access Token.

**When to use:**
- The user mentions a Figma file, frame, component, or comment
- Inspecting a design document's structure (pages, frames, components)
- Rendering specific nodes to PNG/JPG/SVG/PDF for review, docs, or embeds
- Listing / posting / resolving comments on a design review
- Browsing team projects, project files, or the shared component library

**Decision tree:**
- Reading designs?
  - Whole file tree + metadata → `get_file` with `file_key`
  - Only specific nodes (cheaper than full file) → `get_file_nodes` with `file_key` + `ids`
  - Rendered images of nodes → `get_image` with `file_key`, `ids`, `format` (png|jpg|svg|pdf),
    optional `scale`
- Comments?
  - List all comments on a file → `get_comments`
  - Leave a comment → `post_comment` with `message` (+ optional `client_meta` pinning to a
    node or x/y coord)
  - Resolve a comment → `resolve_comment` with `comment_id` (DELETE semantics in Figma)
- Workspace introspection?
  - Projects in a team → `get_team_projects` with `team_id`
  - Files in a project → `get_project_files` with `project_id`
  - Shared components in a team library → `get_team_components` with `team_id`

**Rules:**
- Never ask the user for a token in chat — use the configured credential record
  (Figma uses the `X-Figma-Token` header with a Personal Access Token; not Bearer)
- Prefer `get_file_nodes` over `get_file` when you already have node IDs — the full file
  response is large and can be hundreds of kB
- For destructive writes (`resolve_comment`) confirm intent with `request_human_review` first
  if not explicitly authorized in the prompt
- On rate limit (HTTP 429) the tool returns `retry_after_seconds` — back off instead of
  retrying in a tight loop
- Always include the `file_key` for file-scoped actions — fail fast rather than guessing
""".strip()
