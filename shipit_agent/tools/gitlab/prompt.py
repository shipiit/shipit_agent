from __future__ import annotations

GITLAB_PROMPT = """

## gitlab
Work with GitLab issues, merge requests, repository files, and CI pipelines on
gitlab.com or a self-hosted GitLab instance.

**When to use:**
- The user asks about GitLab issues, MRs, CI pipelines, or repository files
- Looking up an issue or MR by project path and internal id (`!123`)
- Triaging pipelines — listing, retrying, or cancelling failed jobs
- Creating, commenting on, closing issues, or approving / merging MRs

**Decision tree (pick one `action`):**
- Search across all visible issues → `search_issues` (no project needed)
- Fetch a specific issue → `get_issue` with `project_id` + `iid`
- File a new issue → `create_issue` with `project_id`, `title`, `description`
- Close an issue → `close_issue`
- Comment on an issue → `comment_issue` with `body`
- List MRs in a project → `list_merge_requests` with optional `state`
- Fetch one MR → `get_merge_request` with `project_id` + `mr_iid`
- Open a new MR → `create_merge_request` with branches + `title`
- Merge / approve / comment → `merge_merge_request`, `approve_merge_request`,
  `comment_merge_request`
- Read a file → `get_file` with `path` and `ref` (response is base64-decoded)
- CI lookup → `list_pipelines`, `get_pipeline`
- CI control → `retry_pipeline`, `cancel_pipeline`

**Rules:**
- `project_id` may be a numeric id (e.g. `278964`) or a path (`myorg/myrepo`).
  Paths are URL-encoded automatically — do not pre-encode.
- `iid` / `mr_iid` are the *in-project* numbers shown in the UI (`!42`),
  not the global GitLab id.
- `labels` must be a comma-separated string per the GitLab REST contract.
- Do not ask the user for a personal access token — use connector credentials.
- Before destructive actions (close, merge, cancel), confirm via
  `request_human_review`.
- On `rate_limited` errors, respect the `retry_after_seconds` hint.
""".strip()
