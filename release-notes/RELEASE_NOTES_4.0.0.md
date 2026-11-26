# shipit-agent 4.0.0 — Safe by default

An agent reads things you don't control: web pages, files, tool results. Any of
them can try to steer the model. 4.0 assumes that. The safe choice is now the
one you get without asking, and there is a second way to drive the same loop:
an async API with typed messages.

```python
import asyncio

from shipit_agent.sdk import AgentOptions, ResultMessage, query


async def main() -> None:
    options = AgentOptions(
        cwd=".",
        allowed_tools=["Read", "Grep", "Edit", "Bash(pytest *)"],  # everything else asks first
        max_budget_usd=1.0,
    )
    async for message in query(prompt="Run the tests and fix what fails.", options=options):
        if isinstance(message, ResultMessage):
            print(message.subtype, message.num_turns, "turns", message.total_cost_usd)


asyncio.run(main())
```

53 changes: 22 security, 21 added, 1 changed, 9 fixed. The
[changelog](../CHANGELOG.md) has every entry.

## Do you need to change anything?

Most code built on the `Agent` class runs unchanged.

| If your code… | What to do |
| :- | :- |
| Uses `Agent` with built-in tools, on public websites and your project folder | Nothing |
| Lets the agent open URLs inside your own network | Pass `allow_private_hosts=True` to that tool |
| Registers an `async def` function on `AgentHooks` | Make it a plain `def` |
| Runs `shipit serve` on any address but `127.0.0.1` | Pass `--api-key` or set `SHIPIT_API_KEY` |
| Uses the SDK API (`query`, `AgentClient`, `shipit sdk`) | Name the tools you approve; see below |

[Upgrading to 4.0](../docs/guides/upgrading-4.md) has the edit for each case.

## The one breaking change

In the SDK API, a tool that no rule allows no longer runs. Reads and searches
still run freely. Any other call needs a rule in `allowed_tools`, a permission
mode that covers it, or a yes from `can_use_tool`. A call that nothing approves
is not run, and the model is told why. `permission_mode="bypassPermissions"`
restores the old behaviour. The `Agent` class is not affected.

## Safe by default

- **URL tools stay on the public internet.** `open_url`, `fetch_url`,
  `download_file`, `pdf`, `research_brief` and the browser tools refuse private,
  loopback and cloud-metadata addresses, on every redirect, and connect to the
  address they checked.
- **File tools stay in the project.** Downloads and local PDFs are held to the
  project root, and `Edit(...)`, `Write(...)` and `Read(...)` rules cover them.
- **The server needs a key off this machine.** `shipit serve` refuses to start
  on any address but `127.0.0.1` without one, and checks the `Host`, `Origin`
  and `Content-Type` of every request.
- **An async hook is an error, not a silent pass.** An `async def` callback on
  `AgentHooks` used to be skipped, so an async deny hook let every call through.
  It now raises `TypeError`.
- **Traces can be scrubbed before they leave.** `RedactingTraceStore` wraps any
  exporter and replaces secrets, and with `pii=True` emails, phone and card
  numbers.
- **MCP servers are checked more closely.** A reply must answer the request it
  was sent, listings are bounded, and `readOnlyHint` counts only as JSON `true`.

## The async SDK API

`shipit_agent.sdk` runs on shipit's own loop, so it works with every model
provider.

- `query()` for one run and `AgentClient` for a conversation you keep open.
- Typed messages, with text and tool input streaming as they are written.
- Twelve hook events, `SessionStart` and `SessionEnd` among them.
- Your own tools served in process with `@tool` and `create_sdk_mcp_server`.
- A task list (`TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`), `Monitor`
  for watching a command, and background task messages.
- `shipit sdk "prompt"` runs it from the terminal.

## New for the `Agent` class

- `chat.asend()`, `chat.astream()` and `chat.astream_packets()` for async code.
- All thirteen hook points are documented, `on_user_prompt`,
  `on_post_tool_failure` and `on_permission_request` among them.
- `recall_tool_result(query=...)` returns the excerpt around a match in a large
  earlier result.
- `Agent(stream_tool_input_json=True)` emits tool arguments as they are written.
- `AnthropicChatLLM(cache_ttl="1h")` keeps the cached prefix for an hour.

## Fixed

- A token budget is no longer bypassed when a provider leaves out a token count.
- An edit with an empty `old_text` no longer rewrites the file.
- Closing `agent.astream()` early closes the run underneath it.
- A streamed tool call keeps one id from start to finish.
- Forking or resuming a session at a tool call keeps that call's results.
- A server error with no status is retried.
- Session ids such as `team/chat` and `team_chat` no longer share a file.

## Try it

Three guide notebooks run the new features against real models and keep their
output, in `notebooks/guides/`:

- `14_async_sdk_api.ipynb`: the SDK API from a first run to a kept-open conversation.
- `15_secure_by_default.ipynb`: each safe default refusing something, and the line that changes it.
- `16_tasks_background_async.ipynb`: task lists, watched commands, background work and async chat.

## Compatibility

Python 3.11 to 3.14. The `pdf`, `files`, `browser` and `rag-pdf` extras need
`pypdf>=6.21.4`, and the LiteLLM-based extras need `litellm>=1.96.2`.

```bash
pip install -U shipit-agent
```
