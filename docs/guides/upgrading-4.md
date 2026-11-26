---
title: Upgrading to 4.0
description: What 4.0 changes in code you already have, which of it needs an edit, and how to check an upgrade.
---

# Upgrading to 4.0

4.0 has one breaking change in the SDK API and a set of safer defaults. Most code that uses the `Agent` class runs unchanged. This page lists everything that can behave differently, with the edit that restores the old behaviour where you want it.

## Do you need to change anything?

| If you use | What changes | What to do |
| :- | :- | :- |
| `shipit_agent.sdk` (`query`, `AgentClient`, `shipit sdk`) | A tool that no rule allows no longer runs | [Name the tools you approve](#sdk-agents-ask-before-running-a-tool) |
| `include_partial_messages` | Events are framed like the API stream | [Read `content_block_delta` events](#partial-messages-are-framed) |
| `shipit serve` on any address but `127.0.0.1` | It refuses to start without a key | [Pass a key](#the-server-needs-a-key-off-this-machine) |
| URL, browser or PDF tools inside your own network | Private addresses are refused | [Opt out per tool](#url-tools-stay-on-the-public-internet) |
| `AgentHooks` with an `async def` callback | It raises `TypeError` | [Make it a plain function](#an-async-hook-is-an-error) |
| The `pdf`, `files`, `browser`, `rag-pdf` or LiteLLM extras | Newer minimum versions | [Reinstall the extra](#dependency-minimums) |
| Only the `Agent` class, on the public internet | Nothing you need to edit | Read [what is new](#new-in-40) |

## SDK agents ask before running a tool

This is the breaking change. Before 4.0, a tool that no rule mentioned ran. Now reads and searches run freely, and any other call needs one of three things: a rule in `allowed_tools`, a permission mode that covers it, or a yes from `can_use_tool`.

```python
from shipit_agent.sdk import AgentOptions, PermissionResultAllow, PermissionResultDeny


async def can_use_tool(tool_name, tool_input, context):
    if tool_name == "bash" and "deploy" in tool_input.get("command", ""):
        return PermissionResultDeny(message="No deploys from the agent.")
    return PermissionResultAllow()


options = AgentOptions(
    allowed_tools=["Edit", "Bash(pytest *)", "mcp__shop__refund"],  # approved by name
    permission_mode="acceptEdits",                                   # or by mode
    can_use_tool=can_use_tool,                                       # or in code
)
```

A call that nothing approves is not run, and the model is told why, so it can carry on or say what it could not do. A before-tool hook that allows a call counts as approval. The `Agent` class is unchanged: its permission mode and rules behave as in 3.x.

## Partial messages are framed

`include_partial_messages=True` used to yield bare text deltas. Each response is now `message_start`, then every block as `content_block_start`, `content_block_delta` and `content_block_stop`, then `message_delta` and `message_stop`. Tool input streams as `input_json_delta`.

```python
from shipit_agent.sdk import AgentOptions, StreamEvent, query

options = AgentOptions(include_partial_messages=True)

async for message in query(prompt="Explain this project in two sentences.", options=options):
    if isinstance(message, StreamEvent) and message.event.get("type") == "content_block_delta":
        delta = message.event.get("delta", {})
        if delta.get("type") == "text_delta":
            print(delta["text"], end="")
```

## The server needs a key off this machine

`shipit serve` on `127.0.0.1` is unchanged. Bound to any other address it refuses to start without `--api-key` or `SHIPIT_API_KEY` (`api_key=` in code). It never generates one. Every POST must be `application/json`, and a browser origin must be named with `--allow-origin`.

```bash
shipit serve --host 0.0.0.0 --port 8399 --api-key "$SHIPIT_API_KEY" --allow-origin https://app.example.com
```

## URL tools stay on the public internet

`open_url`, `fetch_url`, `download_file`, `pdf`, `research_brief` and the browser tools refuse private, loopback, link-local and cloud-metadata addresses, on every redirect. An agent that works inside your own network opts out, one tool at a time:

```python
from shipit_agent.tools.open_url import OpenURLTool

intranet = OpenURLTool(allow_private_hosts=True)
```

File tools are stricter too. `download_file` writes only inside its downloads folder, the PDF tool reads local files only inside the project, and `Edit(...)`, `Write(...)` and `Read(...)` rules now cover them. An `edit_file` or `multi_edit` call with an empty `old_text` is refused instead of rewriting the file.

## An async hook is an error

A callback on `AgentHooks` written as `async def` used to be skipped without a word, so an async deny hook let every call through. It now raises `TypeError` the first time it runs. Make it a plain function, or use the SDK API's hooks, which are async:

```python
from shipit_agent import AgentHooks

hooks = AgentHooks()


@hooks.on_before_tool
def no_deletes(name: str, arguments: dict) -> dict | None:  # def, not async def
    if name == "bash" and "rm " in arguments.get("command", ""):
        return {"decision": "deny", "reason": "No deletes."}
    return None
```

## MCP servers are checked more closely

- A tool counts as read-only only when its `readOnlyHint` is JSON `true`. The string `"false"` no longer passes.
- An HTTP reply must be a JSON-RPC object with the id of the request and a `result`. Anything else raises `MCPError`.
- Discovery stops after `max_discovery_pages` pages (100 by default) on `RemoteMCPServer`.
- A deny rule for a whole server (`mcp__secrets__*`) also closes it to `list_mcp_resources` and `read_mcp_resource`.

A well-behaved server needs no change.

## Dependency minimums

The `pdf`, `files`, `browser` and `rag-pdf` extras need `pypdf>=6.21.4`, and the LiteLLM-based extras need `litellm>=1.96.2`. Both skip releases with known vulnerabilities. Reinstall the extra you use:

```bash
pip install --upgrade 'shipit-agent[pdf]'
```

## New in 4.0

- **Session hooks:** `SessionStart` and `SessionEnd` in the SDK API. See [Agent SDK API](agent-sdk.md#session-start-and-end).
- **Async chat:** `chat.asend()`, `chat.astream()` and `chat.astream_packets()`. See [Sessions](../agent/sessions.md#from-async-code).
- **Tasks and watching:** the task-list tools, `monitor` and background task messages. See [Agent SDK API](agent-sdk.md#a-task-list).
- **Scrubbed traces:** `RedactingTraceStore` wraps any exporter. See [Security](../security.md#scrub-traces-before-they-leave).
- **Every hook point on `Agent`:** the [hooks guide](hooks.md#hook-types) now lists all thirteen.

Three notebooks run all of this against real models and keep the output: *The async SDK API*, *Secure by default* and *Tasks, background work and async chat*, in `notebooks/guides/`.

## Checking an upgrade

Run your own tests first. Then the benchmark, which runs real tasks against a model and reports what each cost; see [the benchmark guide](benchmark.md):

```
python -m scripts.bench.run --dry-run                    # wiring only, free
python -m scripts.bench.run bedrock google.gemma-4-31b   # a live run
```

Coming from 2.x? Read [Upgrading to 3.0](upgrading.md) first.
