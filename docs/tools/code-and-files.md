---
title: Code & Files
description: Tools for executing code, managing workspace files, storing memory facts, and building artifacts.
---

# Code & Files

Tools that interact with the local filesystem and runtime environment. Use these when the agent needs to **do work** rather than just talk about it.

| Tool | Tool ID | Purpose |
|---|---|---|
| `BashTool` | `bash` | Run bounded shell commands under `project_root` |
| `FileReadTool` | `read_file` | Read project files with optional line ranges |
| `EditFileTool` | `edit_file` | Apply exact string replacement patches to existing files |
| `FileWriteTool` | `write_file` | Create or overwrite project files |
| `GlobSearchTool` | `glob_files` | Find files by glob pattern under `project_root` |
| `GrepSearchTool` | `grep_files` | Search file contents with ripgrep or Python fallback |
| `CodeExecutionTool` | `run_code` | Execute Python or shell code in a sandboxed subprocess |
| `WorkspaceFilesTool` | `workspace_files` | Read, write, list, and inspect files |
| `MemoryTool` | `memory` | Store and retrieve persistent memory facts |
| `ArtifactBuilderTool` | `build_artifact` | Create named artifacts (markdown, JSON, code files) |

The built-in project tools use `project_root="/tmp"` by default. Override this on `Agent` or `DeepAgent` when you want them scoped to a repo checkout instead.

See the dedicated prompt pages for the exact shipped instructions:

- [`bash`](bash.md)
- [`read_file`](read-file.md)
- [`edit_file`](edit-file.md)
- [`write_file`](write-file.md)
- [`glob_files`](glob-files.md)
- [`grep_files`](grep-files.md)

---

## `run_code`

**Class:** `CodeExecutionTool`
**Module:** `shipit_agent.tools.code_execution`
**Tool ID:** `run_code`

Executes Python or shell code in a **local subprocess workspace**. Captures stdout, stderr, and exit code. Times out after a configurable wall-clock limit.

### When to use

- Math and data analysis the LLM shouldn't do in its head (`17 * 23` is fine; matrix algebra isn't)
- File processing — parse a CSV, transform JSON, run a regex
- Verifying claims by **running the actual code**
- Building small one-off scripts the agent then executes

### Schema

```json
{
  "name": "run_code",
  "parameters": {
    "type": "object",
    "properties": {
      "language": { "type": "string", "enum": ["python", "bash"] },
      "code":     { "type": "string", "description": "The code to execute" },
      "timeout":  { "type": "number", "description": "Wall-clock timeout in seconds (default 30)" }
    },
    "required": ["code"]
  }
}
```

### Configuration

```python
from shipit_agent import CodeExecutionTool

tool = CodeExecutionTool(
    workspace_root=".shipit_workspace/code_execution",  # where files live
    timeout=30.0,                                        # default per-call timeout
    python_executable="python3",                         # which Python to use
    allow_shell=True,                                    # set False to disable bash
)
```

### Example

```python
from shipit_agent import Agent, CodeExecutionTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[CodeExecutionTool()],
)

result = agent.run(
    "Calculate the standard deviation of [12, 17, 23, 31, 42, 58]. "
    "Use the code interpreter to verify."
)
```

### Output structure

`ToolOutput.text` is the captured stdout. `ToolOutput.metadata` contains:

| Field | Type | Description |
|---|---|---|
| `language` | str | `"python"` or `"bash"` |
| `exit_code` | int | Subprocess exit code |
| `stdout` | str | Captured standard output |
| `stderr` | str | Captured standard error |
| `duration_seconds` | float | Wall-clock execution time |
| `timed_out` | bool | True if killed by timeout |

### Security notes

⚠️ **`run_code` runs untrusted code in a subprocess.** It's not a security sandbox. The subprocess inherits your environment variables, can access the filesystem under `workspace_root`, and can make network requests.

For production deployments where the LLM is exposed to untrusted prompts:

- Run shipit-agent **inside a Docker container** with no host filesystem mounts
- Restrict the workspace to a tmpfs volume
- Drop network access from the container
- Set `allow_shell=False` if you don't need bash
- Consider running each agent invocation in a fresh container

For local dev and trusted internal use, the default config is fine.

---

## `workspace_files`

**Class:** `WorkspaceFilesTool`
**Module:** `shipit_agent.tools.workspace_files`
**Tool ID:** `workspace_files`

Read, write, list, and inspect files in a **scoped workspace directory**. Supports text and binary modes, append-or-overwrite semantics, and recursive listing.

### When to use

- The agent needs to **stash intermediate results** between tool calls
- A tool produced output that another tool needs to read later
- You want to **persist artifacts** across agent runs
- Multi-step workflows where data flows through files

### Schema

```json
{
  "name": "workspace_files",
  "parameters": {
    "type": "object",
    "properties": {
      "action": { "type": "string", "enum": ["read", "write", "append", "list", "delete", "exists"] },
      "path":   { "type": "string", "description": "Relative path within the workspace" },
      "content": { "type": "string", "description": "Content to write (for write/append actions)" }
    },
    "required": ["action", "path"]
  }
}
```

### Configuration

```python
from shipit_agent import WorkspaceFilesTool

tool = WorkspaceFilesTool(
    root_dir=".shipit_workspace",   # workspace root — all paths resolved relative to this
    max_file_size_bytes=1_000_000,  # cap on read/write sizes
)
```

### Example

```python
from shipit_agent import Agent, WorkspaceFilesTool, CodeExecutionTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[WorkspaceFilesTool(), CodeExecutionTool()],
)

result = agent.run(
    "Generate a CSV of the first 100 prime numbers, save it to primes.csv, "
    "then read it back and tell me the sum."
)
# The agent will:
#   1. run_code → generate primes
#   2. workspace_files write → save to primes.csv
#   3. workspace_files read → load it back
#   4. run_code → compute the sum
```

### Path safety

The tool **rejects paths outside `root_dir`** — attempts at `../../../etc/passwd` get an error. All paths are resolved with `Path.resolve()` and checked against the workspace root.

---

## `memory`

**Class:** `MemoryTool`
**Module:** `shipit_agent.tools.memory`
**Tool ID:** `memory`

Stores and retrieves **structured memory facts** that persist across turns within a session and (optionally) across sessions when paired with `FileMemoryStore`.

### When to use

- The user told the agent something earlier (their name, preferences, project context) and you want it remembered
- The agent learned a fact from a tool call that should be available in future runs
- You're building a long-running assistant that needs **persistent state**

### Schema

```json
{
  "name": "memory",
  "parameters": {
    "type": "object",
    "properties": {
      "action":   { "type": "string", "enum": ["store", "retrieve", "list", "search"] },
      "fact":     { "type": "string", "description": "The fact to store (for store action)" },
      "category": { "type": "string", "description": "Category tag for the fact" },
      "query":    { "type": "string", "description": "Search query (for search action)" }
    },
    "required": ["action"]
  }
}
```

### Configuration

The tool reads/writes to `context.state["memory_store"]` which the runtime populates from `agent.memory_store`. Configure at the Agent level:

```python
from shipit_agent import Agent, FileMemoryStore, MemoryTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[MemoryTool()],
    memory_store=FileMemoryStore(root=".shipit_memory"),  # persistent across runs
)
```

### Example

```python
# Turn 1
agent.run("My name is Alice and I prefer markdown over plain text.")
# Agent stores: name="Alice", format_preference="markdown"

# Turn 2 (even after restart)
agent.run("Send me a summary of the latest news.")
# Agent recalls Alice's preference and returns markdown
```

### Notes

- The runtime **auto-stores tool results** as memory facts after every run, so even without explicit `memory` calls, your tool outputs become recall-able context for future turns
- For semantic search across memory, the `MemoryTool.search` action does substring matching by default — for true semantic search, swap in a custom `MemoryStore` backed by a vector DB

---

## `build_artifact`

**Class:** `ArtifactBuilderTool`
**Module:** `shipit_agent.tools.artifact_builder`
**Tool ID:** `build_artifact`

Creates a **named artifact** — a markdown report, JSON blob, code file, or any other deliverable — and saves it to the workspace with structured metadata. The runtime tracks artifacts on `AgentResult.artifacts` for downstream consumers.

### When to use

- The agent's **final output is a file** (a report, a generated codebase, a data export)
- You want the artifact tracked separately from the conversation history
- The user wants to **download** the deliverable, not just read it inline

### Schema

```json
{
  "name": "build_artifact",
  "parameters": {
    "type": "object",
    "properties": {
      "name":        { "type": "string", "description": "Artifact name (without extension)" },
      "format":      { "type": "string", "enum": ["markdown", "json", "code", "html", "text"] },
      "content":     { "type": "string", "description": "The artifact body" },
      "description": { "type": "string", "description": "What this artifact is" }
    },
    "required": ["name", "format", "content"]
  }
}
```

### Configuration

```python
from shipit_agent import ArtifactBuilderTool

tool = ArtifactBuilderTool(
    workspace_root=".shipit_workspace/artifacts",
)
```

### Example

```python
from shipit_agent import Agent, ArtifactBuilderTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[ArtifactBuilderTool()],
)

result = agent.run(
    "Write a 500-word markdown report on Python type hints and save it as "
    "an artifact named 'python-types-report'."
)

# The artifact is now on result.artifacts
for artifact in result.artifacts:
    print(f"{artifact.name}.{artifact.format} → {artifact.path}")
    print(f"  size: {len(artifact.content)} bytes")
    print(f"  description: {artifact.description}")
```

### Output

`ToolOutput.metadata` contains:

| Field | Type | Description |
|---|---|---|
| `name` | str | Artifact name |
| `format` | str | One of `markdown`, `json`, `code`, `html`, `text` |
| `path` | str | Filesystem path where it was saved |
| `size_bytes` | int | Content size |
| `description` | str | Optional description |

The artifact is also added to `RuntimeState.artifacts` and surfaces on `AgentResult.artifacts` for the caller to enumerate.

---

## Common patterns

### Build → execute → verify pipeline

```
build_artifact (write code)
    ↓
run_code (execute it)
    ↓
verify_output (check it works)
```

Useful for code generation tasks: the agent writes code, runs it, and verifies the output before claiming the task is done.

### Stash → process → report pipeline

```
web_search + open_url (gather raw data)
    ↓
workspace_files write (stash to disk)
    ↓
run_code (process the data)
    ↓
build_artifact (final report)
```

Useful for data analysis tasks where intermediate results are too big to keep in conversation context.

---

## Next: [Connectors →](connectors.md)
