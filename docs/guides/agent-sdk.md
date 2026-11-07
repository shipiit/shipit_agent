# The SDK API

`shipit_agent.sdk` is shipit's own SDK layer, running on shipit's own agent
loop. It doesn't use or depend on the Claude Agent SDK. Its names and message
shapes follow that SDK's Python package on purpose: anyone who knows that SDK
can use shipit straight away, and code written for it ports by changing the
import. It runs on every provider shipit supports: Anthropic, OpenAI,
Bedrock (gpt-oss, Gemma 4 and the rest), Gemini, Vertex, and others through
LiteLLM.

```python
import asyncio

from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, TextBlock, query


async def main() -> None:
    options = AgentOptions(
        model="claude-opus-5-5",
        cwd="/path/to/repo",
        allowed_tools=["Read", "Grep", "Bash(pytest *)"],
        permission_mode="acceptEdits",
        max_budget_usd=2.0,
    )
    async for message in query(prompt="Fix the failing test in tests/test_api.py", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(message.subtype, message.num_turns, message.total_cost_usd)


asyncio.run(main())
```

Every option lands on an `Agent` setting (`build_agent(options)` returns that
agent), so this is the same loop as `Agent.run()`, not a second one.

## Options

| Option | What it does |
| :- | :- |
| `model` | A model id. The provider comes from its name: `claude-*` uses Anthropic, `gpt-*` and `o1`/`o3`/`o4` use OpenAI, `bedrock/...` uses Bedrock, and anything else uses LiteLLM. To use an adapter you built, pass it as `llm`. |
| `fallback_model` | Used when the model fails after its retries. Takes a model id, ids separated by commas, an adapter, or a list of them. |
| `system_prompt` | A string, or `{"type": "preset", "preset": "claude_code", "append": ...}`, `{"type": "custom", "prompt": ...}` or `{"type": "file", "path": ...}`. |
| `tools` | Omitted: the core set (read, edit, write, multi-edit, notebook edit, bash, glob, grep, web search, fetch, todo, ask, memory). `"all"`: every built-in tool. Or a list of tool objects and names; SDK names such as `"Bash"` and `"Read"` work. |
| `allowed_tools` | Rules that pre-approve calls. They don't restrict the other tools. |
| `disallowed_tools` | A bare name removes the tool. A scoped rule (`"Bash(rm *)"`) denies matching calls in every mode. |
| `permission_mode` | `default`, `acceptEdits`, `plan`, `dontAsk` or `bypassPermissions`. |
| `can_use_tool` | Decides calls that no rule, mode or hook settled. |
| `hooks` | `{"PreToolUse": [HookMatcher(...)], ...}`, or an `AgentHooks`. |
| `mcp_servers` | `{name: config}`: stdio, sse, http or `create_sdk_mcp_server(...)`. |
| `agents` | Sub-agent definitions (`description`, `prompt`, `tools`, `model`). |
| `max_turns`, `max_budget_usd` | The step limit and the spend limit. |
| `output_format` | `{"type": "json_schema", "schema": {...}}`. The parsed answer is in `ResultMessage.structured_output`. |
| `include_partial_messages` | Also yield `StreamEvent` text deltas. |
| `resume`, `fork_session`, `session_store`, `session_id` | Continue a saved session, or a copy of it. |
| `continue_conversation` | Continue the most recently saved session in `session_store`. |
| `enable_file_checkpointing` | Record files before the file tools change them, for `rewind_files`. |
| `cwd`, `add_dirs` | The project root, and folders beside it the file tools may also use. |
| `env` | Environment variables for the commands bash and code execution run, never this process's own. |
| `effort`, `thinking`, `max_thinking_tokens`, `betas` | Passed to adapters that take them (Anthropic does). A thinking budget becomes adaptive thinking on models that reject budgets. |
| `agent_options` | Any other `Agent` setting, under its shipit name. |

## Messages

A run yields these messages:

1. A `SystemMessage` with subtype `init`. Its `data` holds the model, tools, MCP servers, permission mode, working directory and session id.
2. An `AssistantMessage` for each model response. Its content blocks are `TextBlock`, `ThinkingBlock` and `ToolUseBlock`.
3. A `UserMessage` for each tool result, as a `ToolResultBlock` with `is_error` set on failures and denials.
4. Other `SystemMessage`s along the way: `compact_boundary`, `api_retry` and `model_fallback`.
5. One `ResultMessage` at the end.

The `ResultMessage` reports how the run went:

- **How it ended:** `subtype` is one of `success`, `error_max_turns`, `error_max_budget_usd`, `error_max_budget_tokens`, `error_during_execution` or `error_max_structured_output_retries`. `is_error` says whether the run stopped short.
- **Answer:** `result` and `structured_output`.
- **Effort and cost:** `num_turns`, `duration_ms`, `duration_api_ms`, `total_cost_usd` and `usage`.
- **Other details:** `stop_reason` and `permission_denials`.

A run that raises still ends with a `ResultMessage`, with subtype `error_during_execution` and the error in `errors`.

The same fields are on `AgentResult` when you use `Agent.run()`. The same model responses arrive there as `assistant_message` events.

## Custom tools

```python
from shipit_agent.sdk import AgentOptions, create_sdk_mcp_server, tool


@tool("add", "Add two numbers", {"a": float, "b": float})
async def add(args):
    return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}


calc = create_sdk_mcp_server("calc", tools=[add])
options = AgentOptions(mcp_servers={"calc": calc}, allowed_tools=["mcp__calc__add"])
```

- **Schema:** a full JSON Schema works as well as the `{"name": type}` shorthand.
- **Errors:** return `"is_error": True` to report a failure the model can act on.
- **Naming:** a server's tools are exposed as `<server>__<tool>`; rules may name them either way.

External servers use the same `mcp_servers` dict:

```python
mcp_servers = {
    "files": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
    "docs": {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ..."}},
}
```

## Permission rules

Rules are checked in the SDK's order:

1. Hooks.
2. Deny rules.
3. Ask rules.
4. The permission mode.
5. Allow rules.
6. `can_use_tool`.

| Rule | Covers |
| :- | :- |
| `Bash` | every bash call |
| `Bash(rm *)` | bash calls whose command matches `rm *` as written |
| `Bash(npm run test:*)` | bash commands starting with `npm run test` |
| `Edit(src/**)` | writes under `<cwd>/src`, by any file-writing tool |
| `Edit(//etc/**)` | writes under `/etc` (`//` is absolute) |
| `Read(~/.ssh/**)` | reads under the home directory's `.ssh` |
| `WebFetch(domain:example.com)` | fetches from `example.com` |
| `mcp__github__*` | every tool from the `github` MCP server |

A compound command is judged part by part. A deny rule matches when any part matches, and an allow rule only when every part does, so `Bash(ls *)` can't approve `ls && rm -rf x`. Paths are normalised first, so `src/../secrets` isn't under `src/**`.

## Approvals

```python
from shipit_agent.sdk import PermissionResultAllow, PermissionResultDeny


async def can_use_tool(tool_name, input_data, context):
    if tool_name == "bash" and "deploy" in input_data.get("command", ""):
        return PermissionResultDeny(message="No deploys from the agent.")
    return PermissionResultAllow(updated_input=input_data)
```

`updated_input` rewrites the call. An `addRules` allow in `updated_permissions` approves this call for the rest of the session.

Calls that need no approval, such as reads and searches, are approved without calling `can_use_tool`, as in the SDK.

## Clarifying questions

When the model asks the user something, `can_use_tool` is called with `tool_name == "AskUserQuestion"`. The input holds `questions`, each with `question`, `header`, `options` (a `label` and a `description` each) and `multiSelect`. Answer by echoing the questions with an `answers` map from question text to the chosen label (a list for multi-select), or with a free-form `response`:

```python
async def can_use_tool(tool_name, input_data, context):
    if tool_name == "AskUserQuestion":
        first = input_data["questions"][0]
        return PermissionResultAllow(updated_input={
            "questions": input_data["questions"],
            "answers": {first["question"]: first["options"][0]["label"]},
        })
    return PermissionResultAllow(updated_input=input_data)
```

A denial, or a run with no `can_use_tool`, tells the model to state its assumption and carry on.

## Streaming input

`query()` and `client.query()` also take an async iterable of SDK user messages. Each message runs as a turn of the same conversation:

```python
async def messages():
    yield {"type": "user", "message": {"role": "user", "content": "Read app.py"}}
    yield {"type": "user", "message": {"role": "user", "content": "Now add tests for it"}}

async for message in query(prompt=messages(), options=options):
    ...
```

## Hooks

```python
from shipit_agent.sdk import HookMatcher


async def no_secrets(input_data, tool_use_id, context):
    if ".env" in str(input_data["tool_input"]):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "deny",
                                       "permissionDecisionReason": "No .env files."}}
    return {}


options = AgentOptions(hooks={"PreToolUse": [HookMatcher("Read|Edit", [no_secrets], timeout=5)]})
```

All ten events work: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `Notification` and `PermissionRequest`.

- **Inputs and outputs:** they use the SDK's field names, including `permissionDecision`, `updatedInput`, `updatedToolOutput`, `additionalContext` and `decision: "block"`.
- **Failures:** a hook that raises or times out is skipped, unless its matcher sets `on_failure="block"`.
- **Without the SDK layer:** the same events exist natively on `AgentHooks`, as `on_post_tool_use`, `on_post_tool_failure`, `on_permission_request` and `on_notification`.

## A conversation

```python
from shipit_agent.sdk import AgentClient, AgentOptions

async with AgentClient(AgentOptions(cwd=".", enable_file_checkpointing=True)) as client:
    await client.query("Refactor utils.py")
    async for message in client.receive_response():
        ...
    await client.set_permission_mode("acceptEdits")
    await client.query("Now update the tests")      # the same conversation
    turn = [m async for m in client.receive_response()]
    await client.rewind_files(turn[0].uuid)          # undo that turn's file changes
```

The client's methods:

- `interrupt()` stops a turn between steps.
- `set_model(model)` changes the model from the next call; `set_model(None)` goes back to the first one.
- `get_context_usage()` and `get_mcp_status()` report on the session.
- `stop_task(task_id)` stops a background sub-agent.

Each response starts with a `UserMessage` echoing the prompt. Its `uuid` is what `rewind_files` takes.

## Background tasks

Both kinds of background work are tasks: a command started with `bash(background=True)`, or one that outlives its timeout, is `local_bash`, and `sub_agent(background=True)` is `local_agent`. Between steps the runtime checks on them:

- **A new task** emits a `task_started` event.
- **A finished task** emits `task_notification`. If it completed or failed, the model is also told in the conversation, with the output file or a summary, so it can react without polling.

In the SDK stream these are `SystemMessage("task_started")` and `SystemMessage("task_notification")`. `task_stop` (the SDK's `TaskStop`, also matched by `KillShell` and `KillBash`) stops either kind by id, and so does `AgentClient.stop_task(task_id)`. A tool can join in by defining `list_background_tasks()` and `stop_background_task(task_id)` (see `shipit_agent.core.tasks`).

## Deferring a call for later

A `PreToolUse` hook that answers `permissionDecision: "defer"` (or a before-tool hook that returns `{"decision": "defer"}`) pauses the run after that step:

- **When it pauses:** the call doesn't run. The run ends with `stop_reason == "tool_deferred"`, and `deferred_tool_use` holds the call's `id`, `name` and `input`. The call is saved with the session.
- **When you resume:** resume the session with the same `session_id` and `session_store`, or `AgentOptions(resume=...)`. Before the model is called, the hook is asked again. An approval runs the call and puts its result where the call stood; a refusal is recorded there instead; another defer pauses again without calling the model.

Precedence among hook answers is deny, then defer, then ask, then allow. Use this when a person may take longer to decide than the process should stay open. For approvals within the run, use `can_use_tool`. To queue side effects and keep going, use `ApprovalQueue`.

## Plugins and settings files

```python
options = AgentOptions(
    cwd="/path/to/repo",
    plugins=[{"type": "local", "path": "./plugins/deploy-tools"}],
    setting_sources=["project", "local"],
)
```

A plugin is a Claude Code plugin directory:

```text
deploy-tools/
├── .claude-plugin/plugin.json   # optional manifest
├── skills/<name>/SKILL.md       # skill deploy-tools:<name>
├── commands/<name>.md           # command /deploy-tools:<name>
├── agents/<name>.md             # sub-agent deploy-tools:<name>
├── hooks/hooks.json             # command hooks
└── .mcp.json                    # MCP servers
```

Manifest keys work as in Claude Code: `skills` adds to `skills/`, `commands` and `agents` replace their folders, and `hooks` and `mcpServers` merge with the default files. `${CLAUDE_PLUGIN_ROOT}` is filled in in commands, agents and MCP configs, and hook commands get it in their environment. A plugin that doesn't load is reported in the `init` message's `plugin_errors`, as is a path that leaves the plugin directory. The `init` message also lists `plugins`, `skills` and `slash_commands`.

`setting_sources` reads `~/.claude/settings.json` (`user`), `.claude/settings.json` (`project`) and `.claude/settings.local.json` (`local`):

- **Permissions:** the `allow`, `deny` and `ask` lists add up across files, and `defaultMode` comes from the most specific file.
- **Model and env:** `model` is used when no model is given. `env` goes to hook commands only, never this process's environment.
- **Hooks:** every file's hooks run.
- **Commands:** `.claude/commands/*.md` load with `project`.

Command hooks follow Claude Code: the hook input arrives as JSON on stdin.

- **Exit 0:** stdout, if it's one JSON object, is the hook's output. Plain text is added as context for `UserPromptSubmit`.
- **Exit 2:** blocks, with stderr as the reason.
- **Other exits and timeouts:** logged; the run carries on.

Commands run with a minimal environment, so this process's secrets don't leak into them, plus `CLAUDE_PROJECT_DIR` and `CLAUDE_PLUGIN_ROOT`. Hook events and hook types shipit can't run, such as `SessionStart` and `prompt` hooks, are skipped and reported.

The same works without the SDK layer: `Agent(llm=llm, harness=Harness.load(cwd, plugins=[...], setting_sources=[...]))`, and `Agent.run("/deploy-tools:status staging")` expands the command.

## Saved sessions

```python
from shipit_agent.sdk import fork_session, list_sessions, rename_session
from shipit_agent.stores.session import FileSessionStore

store = FileSessionStore(".shipit/sessions")
for info in list_sessions(store):
    print(info.session_id, info.summary)
rename_session(store, session_id, "Release plan")
branch = fork_session(store, session_id)
options = AgentOptions(session_store=store, resume=branch)
```

## Where shipit differs

- **Settings files are opt-in.** The SDK reads project settings by default. shipit reads none unless `setting_sources` names them, because they can run hook commands and a library has no "do you trust this folder?" prompt. Plugins run because you name each one.
- **No CLI process.** shipit runs in your process, so `cli_path`, `extra_args`, `stderr`, `max_buffer_size`, `permission_prompt_tool_name` and `Transport` have no counterpart. Project files (`CLAUDE.md`, `.claude/agents`, `.shipit/skills`) are read directly.
- **Sessions live in a `SessionStore`, not in transcript files.** The agent stamps `updated_at` on each save; `continue_conversation` picks the latest.
- **`continue_: False` in a hook output** refuses that call or prompt; it doesn't end the whole session. `PreToolUse` and `PermissionRequest` callbacks get `tool_use_id=None`.
- **`interrupt=True` from `can_use_tool`** refuses the call; it doesn't end the session.
- **No `sandbox`.** Bash runs under permissions and a secret-free environment, not an OS sandbox.
- **File checkpoints** cover the file tools, not files changed by shell commands. The SDK has the same limit.
