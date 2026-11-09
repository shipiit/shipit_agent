---
description: Run the agent's commands inside the operating system's sandbox, with writes kept to the project and the network off.
---

# Sandbox

With the sandbox on, the commands the agent runs, through `bash` and `run_code`, execute inside the operating system's sandbox: Seatbelt (`sandbox-exec`) on macOS, bubblewrap (`bwrap`) on Linux. A command can read the machine but write only in the project, and it has no network unless you allow it. Because a sandboxed command cannot do lasting damage outside the project, it needs no approval.

```python
from shipit_agent.sdk import AgentOptions

options = AgentOptions(sandbox={"enabled": True})
```

The settings are a plain dict, the same shape whether you pass it to `AgentOptions` or build a `SandboxPolicy` from it.

## What a sandboxed command can do

| | Allowed | Refused |
| :- | :- | :- |
| **Write** | The project, the `add_dirs` folders, the temp folder, `filesystem.allowWrite` | Everything else, and `filesystem.denyWrite` even inside the allowed folders |
| **Read** | Everything | `filesystem.denyRead` |
| **Network** | Only when `network.allowedDomains` has an entry | Otherwise all outbound connections |

```python
options = AgentOptions(sandbox={
    "enabled": True,
    "excludedCommands": ["docker *"],
    "filesystem": {
        "denyWrite": ["/home/me/project/.env"],
        "allowWrite": ["/home/me/.cache/pip"],
    },
    "network": {"allowedDomains": ["pypi.org"], "allowLocalBinding": True},
})
```

## Settings

| Setting | Default | Effect |
| :- | :- | :- |
| `enabled` | `False` | Turns the sandbox on. |
| `autoAllowBashIfSandboxed` | `True` | A command that will run sandboxed needs no approval. Commands blocked outright, such as `rm -rf /`, stay blocked. |
| `excludedCommands` | `[]` | Patterns such as `docker *`. A command runs outside the sandbox only if every part of it matches. |
| `allowUnsandboxedCommands` | `True` | The model may set `dangerouslyDisableSandbox` on one bash call, for a command that failed because of the sandbox. That call needs approval. |
| `failIfUnavailable` | `False` | When no sandbox can run here, fail instead of running commands unsandboxed with a warning. |
| `filesystem.allowWrite` | `[]` | More folders commands may write to. |
| `filesystem.denyWrite` | `[]` | Paths commands may not write, even inside allowed folders. |
| `filesystem.denyRead` | `[]` | Paths commands may not read. |
| `network.allowedDomains` | `[]` | Any entry turns the network on. |
| `network.allowLocalBinding` | `False` | Lets a command listen on localhost, for a dev server. |
| `network.allowUnixSockets` | `[]` | Unix sockets commands may reach (macOS). |
| `network.allowAllUnixSockets` | `False` | Every Unix socket. |

A misspelt setting is an error, so a typo cannot silently weaken the sandbox.

## Limits

- **Domains are not filtered one by one.** Any `allowedDomains` entry turns the network on for every host, and `deniedDomains` is not enforced. Leave `allowedDomains` empty to keep the network off.
- **Platforms.** macOS has `sandbox-exec` built in. On Linux, install bubblewrap (`apt install bubblewrap`). Elsewhere, and on Linux without it, commands run unsandboxed with a warning unless `failIfUnavailable` is set.
- **Accepted for compatibility, with no effect:** `ignoreViolations`, `enableWeakerNestedSandbox`, `allowManagedDomainsOnly`, `allowMachLookup`, `httpProxyPort`, `socksProxyPort`.
- **The file tools are not sandboxed by the OS.** `read_file`, `edit_file` and the others already refuse paths outside the project and `add_dirs`; permissions govern them.

## With the Agent class

The sandbox is a policy on the tools that run commands. Build it from the same settings and give it to them:

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.sandbox import SandboxPolicy
from shipit_agent.tools import BashTool

policy = SandboxPolicy.from_settings({"enabled": True, "filesystem": {"denyWrite": [".env"]}})
agent = Agent(
    llm=build_llm_from_env(),
    tools=[BashTool(root_dir=".", sandbox_policy=policy)],
    project_root=".",
)
```

## What the model sees

When the sandbox is on and unsandboxed commands are allowed, the bash tool's schema gains a `dangerouslyDisableSandbox` flag. A refused write or network call shows up in the command's output as `Operation not permitted` (macOS) or `Read-only file system` (Linux), so the model can tell a sandbox refusal from an ordinary failure.
