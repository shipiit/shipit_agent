---
title: gitlab
description: GitLab v4 REST connector — issues, merge requests, repository files, and CI pipelines on gitlab.com or any self-hosted GitLab instance.
---

# `gitlab`

One tool covering the GitLab developer surface: search and manage
issues, drive merge requests end-to-end (create → approve → merge →
comment), read files at any ref, and control CI pipelines (list,
retry, cancel). Works against `gitlab.com` by default or any
self-hosted GitLab via `base_url`.

> **TL;DR** — configure a `CredentialRecord` under key `gitlab` with a
> personal access token and an optional `base_url`, then call with
> `action="list_merge_requests"`, `project_id="myorg/myrepo"`,
> `state="opened"`.

## When to use

- **Release engineer** driving MRs: `list_merge_requests` →
  `get_merge_request` → `approve_merge_request` →
  `merge_merge_request`.
- **Issue triager** working a project backlog: `search_issues` is
  global, `get_issue` / `create_issue` / `close_issue` /
  `comment_issue` are project-scoped.
- **CI doctor** on a broken pipeline: `list_pipelines` →
  `get_pipeline` → `retry_pipeline` or `cancel_pipeline`.
- **Code reader** that needs a file at a specific ref without
  cloning: `get_file` with `path` and `ref`.
- **Self-hosted GitLab** — override `base_url` to point at your
  instance (e.g. `https://gitlab.mycorp.com`).

## Quick example

```python
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.gitlab import GitLabTool
from shipit_agent.integrations import InMemoryCredentialStore, CredentialRecord

store = InMemoryCredentialStore()
store.set(CredentialRecord(key="gitlab", provider="gitlab",
    secrets={"api_key": "glpat-xxxxxxxxxxxxxxxxxxxx"},
    metadata={"base_url": "https://gitlab.com"},  # optional
))

tool = GitLabTool(credential_store=store)
ctx = ToolContext(prompt="demo")

out = tool.run(ctx, action="list_merge_requests",
               project_id="myorg/myrepo", state="opened")
print(out.text)
# !42 [opened] Fix flaky CI job  https://gitlab.com/myorg/myrepo/-/merge_requests/42
```

## Setup

```python
from shipit_agent.integrations import CredentialRecord

CredentialRecord(key="gitlab", provider="gitlab",
    secrets={"api_key": "<gitlab personal access token>"},
    metadata={
        # Optional — defaults to https://gitlab.com
        "base_url": "https://gitlab.example.com",
    },
)
```

Scopes: `read_api` for read-only, `api` for everything else
(`create_issue`, `merge_merge_request`, `retry_pipeline`, …). The
token is never logged; it is sent as `Authorization: Bearer <token>`.

### `project_id` conventions

The tool accepts either shape; it URL-encodes paths for you, so
**do not pre-encode**:

- Numeric: `"278964"`
- Path: `"myorg/myrepo"` (encoded to `myorg%2Fmyrepo` internally)

`iid` / `mr_iid` / `pipeline_id` are the **in-project** numbers you
see in the UI (`!42`), not the global GitLab database id.

## Actions

All 16 actions share a single `action` enum.

### `search_issues`

Global issue search (no `project_id` required). Required: `query`.
Optional: `per_page` (default 20), `page` (default 1).

```python
tool.run(ctx, action="search_issues", query="flaky test")
```

### `get_issue`

Required: `project_id`, `iid`.

### `create_issue`

Required: `project_id`, `title`. Optional: `description_text`,
`labels` (comma-separated string **or** list — list is joined for
you), `assignee_ids` (list of integers).

```python
tool.run(ctx, action="create_issue",
         project_id="myorg/myrepo",
         title="Pin urllib3 < 2.0",
         description_text="Breaks boto3 on 3.11.",
         labels="bug,deps")
```

### `close_issue`

Required: `project_id`, `iid`. Sends `state_event=close`.

### `comment_issue`

Required: `project_id`, `iid`, `body`.

### `list_merge_requests`

Required: `project_id`. Optional: `state` (`opened` default,
`closed`, `merged`, `all`), `per_page`, `page`.

### `get_merge_request`

Required: `project_id`, `mr_iid`. Returns source / target branch,
state, author, web URL.

### `create_merge_request`

Required: `project_id`, `source_branch`, `target_branch`, `title`.
Optional: `description_text`.

```python
tool.run(ctx, action="create_merge_request",
         project_id="myorg/myrepo",
         source_branch="rahul/fix-42",
         target_branch="main",
         title="Fix flaky CI job",
         description_text="Closes !42.")
```

### `merge_merge_request`

Required: `project_id`, `mr_iid`. Calls
`PUT /projects/:id/merge_requests/:mr_iid/merge` with GitLab defaults.

### `approve_merge_request`

Required: `project_id`, `mr_iid`.

### `comment_merge_request`

Required: `project_id`, `mr_iid`, `body`.

### `get_file`

Required: `project_id`, `path`. Optional: `ref` (default `main`). The
response is base64-decoded and returned as `output.text`; the raw
metadata (including encoding and web URL) is in `metadata.file`.

```python
out = tool.run(ctx, action="get_file",
               project_id="myorg/myrepo",
               path="README.md", ref="main")
```

### `list_pipelines`

Required: `project_id`. Optional: `per_page`, `page`.

### `get_pipeline`

Required: `project_id`, `pipeline_id`.

### `retry_pipeline`

Required: `project_id`, `pipeline_id`. Posts to `/pipelines/:id/retry`.

### `cancel_pipeline`

Required: `project_id`, `pipeline_id`. Posts to `/pipelines/:id/cancel`.

## Error shapes

| `error=` | Meaning | What to do |
| --- | --- | --- |
| `connected: False` (no `error` key) | No credential record for key `gitlab` | Put a record in the store. |
| `rate_limited` | HTTP 429 | `metadata.retry_after_seconds` tells you how long to wait. |
| `http_error` | Any non-2xx from GitLab | `metadata.status` + `metadata.message` carry the parsed `message` / `error` / `error_description` field from the GitLab payload. |
| `unsupported_action` | `action=` value not in the enum | Use one of the 16 listed actions. |
| (missing params) | Action-specific, e.g. "project_id and iid are required for get_issue." | The failing action is echoed in `metadata.action`. |

## Related

- [Tool catalog](index.md) — every built-in tool.
- [GitHub](github.md) — the sibling tool for GitHub.com / Enterprise.
- [Connectors](connectors.md) — credential store setup.
- [Specialists](../autopilot/specialists.md) — reviewer / release-eng
  roles that chain GitLab actions.
