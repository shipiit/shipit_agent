from __future__ import annotations

GITHUB_PROMPT = """

## github
Work with issues, pull requests, file contents, and GitHub Actions workflow runs on a
connected GitHub account (api.github.com by default, or a self-hosted Enterprise base URL).

**When to use:**
- The user mentions GitHub issues, pull requests, reviews, merges, or CI runs
- Reading source files from a repository at a specific ref
- Triaging bugs ("find the open `crash` issues"), shipping a PR, or re-running a failed workflow
- Automating review flows: approve, request changes, or request reviewers on a PR

**Decision tree:**
- Looking things up?
  - Open issues matching a query → `search_issues` with a GitHub `q=` string
  - A single issue → `get_issue` with `owner`, `repo`, `number`
  - PRs on a repo → `list_pulls` (pass `state=open|closed|all`)
  - One PR with diff stats → `get_pull`
  - A file's contents → `get_file` (auto-decodes base64; falls back to download_url if binary)
  - CI runs → `list_workflow_runs` or `get_workflow_run`
- Taking action?
  - File or triage an issue → `create_issue`, `comment_issue`, `close_issue`
  - Ship code → `create_pull`, `update_pull`, `merge_pull` (merge_method: merge|squash|rebase)
  - Review flow → `review_pull` (event: APPROVE|REQUEST_CHANGES|COMMENT) or `request_review`
  - Re-run a failed pipeline → `rerun_workflow`

**Rules:**
- Never ask the user for a token in chat — use the configured credential record
- For destructive writes (merge_pull, close_issue, review_pull with APPROVE) confirm intent with
  `request_human_review` first if the action was not explicitly authorized in the prompt
- On rate limit (403 with X-RateLimit-Remaining: 0) the tool returns `retry_after_epoch`; wait
  until then or summarize the partial results instead of retrying in a tight loop
- Prefer `per_page` ≤ 50 for list endpoints; paginate via the returned `next_url` if present
- Always include `owner` and `repo` — fail fast rather than guessing
""".strip()
