---
title: github
description: GitHub REST API connector — issues, pull requests, reviews, merges, repository file reads, and GitHub Actions workflow runs from a single tool.
---

# `github`

Wrap the GitHub v3 REST API in one tool. Triage issues, open / review /
merge pull requests, read source files at a specific ref, and drive
GitHub Actions workflow runs — all with one auth hop and a stable
`action` enum. Works against `api.github.com` by default or any
self-hosted GitHub Enterprise base URL.

> **TL;DR** — hand the tool a `CredentialRecord` (token + optional
> `base_url`) and call it with `action="search_issues"`,
> `action="get_pull"`, `action="merge_pull"`, etc. Every action returns
> a structured `ToolOutput` with `metadata.item(s)` plus a
> human-readable `text` line.

## When to use

- **PR reviewer / release engineer** shipping code: `list_pulls` →
  `get_pull` → `review_pull` / `merge_pull`.
- **Bug triager** working issue backlogs: `search_issues` →
  `get_issue` → `comment_issue` / `close_issue`.
- **Read-through agents** that need source at a specific commit
  without cloning: `get_file` with `owner`, `repo`, `path`, `ref`.
- **CI doctor** re-running flaky workflows: `list_workflow_runs` →
  `get_workflow_run` → `rerun_workflow`.
- **Automation on GitHub Enterprise** — override `base_url` in the
  credential record to point at a self-hosted instance.

## Quick example

```python
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.github import GitHubTool
from shipit_agent.integrations import InMemoryCredentialStore, CredentialRecord

store = InMemoryCredentialStore()
store.set(CredentialRecord(key="github", provider="github",
    secrets={"api_key": "ghp_xxxxxxxxxxxxxxxxxxxx"},
    metadata={},   # base_url defaults to https://api.github.com
))

tool = GitHubTool(credential_store=store)
ctx = ToolContext(prompt="demo")

out = tool.run(ctx, action="search_issues", query="repo:shipiit/shipit_agent is:open label:bug")
print(out.text)
# #482 [open] autopilot crashes on empty tool list
# #491 [open] bedrock adapter drops trailing tool_result
```

## Setup

The tool is a `HTTPConnectorToolBase`. Credentials go into your
`CredentialStore` under the key `github`:

```python
from shipit_agent.integrations import CredentialRecord

CredentialRecord(key="github", provider="github",
    secrets={"api_key": "<github personal access token or fine-grained token>"},
    metadata={
        # Optional — defaults to https://api.github.com
        "base_url": "https://github.mycorp.com/api/v3",
        # Optional — defaults to "Bearer"
        "auth_scheme": "Bearer",
    },
)
```

Token scopes: `repo` for private repos, `workflow` for
`rerun_workflow`, `public_repo` is enough for read-only on public
repos. The token is never logged; the tool sends it as
`Authorization: Bearer <token>`.

## As a tool handed to an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.tools.github import GitHubTool

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-5.5"),
    tools=[GitHubTool()],
    credential_store=store,
    prompt=(
        "You are a release engineer. Use the github tool to review PRs, "
        "rerun failed workflows, and comment on issues."
    ),
)
agent.run("Find open PRs on shipiit/shipit_agent that touch autopilot/, approve any that already have two +1s.")
```

## Actions

All 16 actions live on a single `action` parameter. Every action
requires `owner` + `repo` except `search_issues` (which uses GitHub's
global search `q=` string).

### `search_issues`

GitHub-wide issue + PR search. Required: `query`. Optional:
`per_page` (default 30), `page` (default 1).

```python
tool.run(ctx, action="search_issues",
         query="repo:shipiit/shipit_agent is:issue is:open label:bug",
         per_page=20)
```

### `get_issue`

Fetch one issue by number. Required: `owner`, `repo`, `number`.

```python
tool.run(ctx, action="get_issue", owner="shipiit", repo="shipit_agent", number=482)
```

### `create_issue`

Required: `owner`, `repo`, `title`. Optional: `body`, `labels` (list
of strings), `assignees` (list of logins).

```python
tool.run(ctx, action="create_issue",
         owner="shipiit", repo="shipit_agent",
         title="Autopilot crashes on empty tool list",
         body="Reproducer in notebook 37.",
         labels=["bug", "autopilot"],
         assignees=["rahul"])
```

### `comment_issue`

Required: `owner`, `repo`, `number`, `body`.

### `close_issue`

Required: `owner`, `repo`, `number`. Marks the issue `state=closed`.

### `list_pulls`

Required: `owner`, `repo`. Optional: `state` (`open` default, `closed`,
`all`), `per_page`, `page`.

```python
tool.run(ctx, action="list_pulls", owner="shipiit", repo="shipit_agent", state="open")
```

### `get_pull`

Fetch one PR with diff stats (`additions`, `deletions`,
`changed_files`). Required: `owner`, `repo`, `number`.

### `create_pull`

Open a new PR. Required: `owner`, `repo`, `title`, `head`, `base`.
Optional: `body`.

```python
tool.run(ctx, action="create_pull",
         owner="shipiit", repo="shipit_agent",
         title="Fix empty-tool-list crash",
         head="rahul/fix-482", base="main",
         body="Closes #482.")
```

### `update_pull`

Required: `owner`, `repo`, `number`, plus at least one of `title`,
`body`, `state`. If all three are omitted the tool returns
`missing_parameter`.

### `merge_pull`

Required: `owner`, `repo`, `number`. Optional: `merge_method` —
one of `merge` (default), `squash`, `rebase`. Any other value
returns `invalid_merge_method`.

```python
tool.run(ctx, action="merge_pull",
         owner="shipiit", repo="shipit_agent",
         number=512, merge_method="squash")
```

### `review_pull`

Required: `owner`, `repo`, `number`, `event` — one of `APPROVE`,
`REQUEST_CHANGES`, `COMMENT`. Case-insensitive; anything else returns
`invalid_event`. Optional: `body` (required when `event` is
`REQUEST_CHANGES` or `COMMENT` if you want the review to say anything).

```python
tool.run(ctx, action="review_pull",
         owner="shipiit", repo="shipit_agent", number=512,
         event="APPROVE", body="LGTM")
```

### `request_review`

Required: `owner`, `repo`, `number`, and a non-empty `reviewers` list
of GitHub logins.

### `get_file`

Read repository file contents. Required: `owner`, `repo`, `path`.
Optional: `ref` (branch, tag, or commit SHA). The tool
base64-decodes the payload and returns the decoded text in
`output.text`. If the file is binary (encoding is not `base64`) the
tool returns `unsupported_encoding` with the `download_url` in metadata
so you can fetch the raw bytes yourself.

```python
out = tool.run(ctx, action="get_file",
               owner="shipiit", repo="shipit_agent",
               path="README.md", ref="main")
print(out.text[:400])
```

### `list_workflow_runs`

Required: `owner`, `repo`. Optional: `per_page`, `page`.

### `get_workflow_run`

Required: `owner`, `repo`, `run_id`.

### `rerun_workflow`

Required: `owner`, `repo`, `run_id`. Posts to `/actions/runs/{id}/rerun`.

## Error shapes

Every error lands in `metadata["error"]` as a stable string. Callers
can branch on it without parsing the human-readable `text`.

| `error=` | Meaning | What to do |
| --- | --- | --- |
| `connected: False` (no `error` key) | No `CredentialRecord` found for key `github` | Put a record in the store before calling. |
| `missing_parameter` | One of the required inputs was blank or missing | `metadata.missing` lists the names. |
| `unsupported_action` | `action=` value not in the enum | Use one of the 16 listed actions. |
| `rate_limited` | HTTP 403 with `X-RateLimit-Remaining: 0` | `metadata.retry_after_epoch` tells you when the window resets. Don't retry in a tight loop. |
| `http_error` | Any other non-2xx from GitHub | `metadata.status` + `metadata.message` carry the GitHub error payload. |
| `request_failed` | Network / transport exception | Transient — retry with backoff. |
| `invalid_merge_method` | `merge_method` not in `merge\|squash\|rebase` | Pass a valid value. |
| `invalid_event` | `event` not in `APPROVE\|REQUEST_CHANGES\|COMMENT` | Pass a valid value. |
| `unsupported_encoding` | `get_file` returned a non-base64 payload (typically a large binary) | Follow `metadata.download_url` for the raw bytes. |
| `decode_failed` | Base64 payload failed to decode | Inspect `metadata.download_url`. |

## Related

- [Tool catalog](index.md) — every built-in tool.
- [Connectors](connectors.md) — credential store, OAuth helpers, other
  SaaS integrations.
- [Specialists](../autopilot/specialists.md) — built-in developer /
  reviewer roles that know how to drive this tool.
- [GitLab](gitlab.md) — the sibling tool with the same shape for
  GitLab.
