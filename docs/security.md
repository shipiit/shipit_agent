# Security

## Reporting a vulnerability

If you believe you have found a security issue, **do not** open a public issue with exploit details.

Please report it privately with:

- a short description of the issue
- affected files or components
- reproduction steps
- impact assessment
- any suggested mitigation

Until a dedicated security contact is published, use the repository maintainer contact channel or a private repository contact method.

## Scope

Areas that deserve extra care in this project:

- **Code execution** — `CodeExecutionTool` runs arbitrary Python in a subprocess. Treat inputs as untrusted.
- **MCP transports and remote tool calls** — outbound HTTP/stdio to untrusted servers.
- **Browser automation** — `PlaywrightBrowserTool` and `OpenURLTool` fetch arbitrary URLs.
- **File workspace access** — `WorkspaceFilesTool` reads/writes files under a scratch root.
- **Credentials** — LLM provider keys, third-party connector tokens, Playwright scraper credentials.

## What's safe by default

- **`.env` is gitignored** — `.env`, `.env.local`, and `.env.*.local` are excluded from version control.
- **Credentials are never logged** — adapters only report provider and model name in `LLMResponse.metadata`. API keys never appear in events, traces, or memory.
- **Notebook credential printers only show `✓ set` / `✗ missing`** — never the actual value. Safe to share notebooks.
- **Default web search provider is DuckDuckGo** — no API key required, no account-linked telemetry.
- **`open_url` fallback is stdlib `urllib`** — no third-party HTTP libraries in the default fetch path.
- **URL tools cannot reach your network.** `open_url`, `fetch_url`, `download_file`, `pdf`, `research_brief`, `playwright_browse` and the computer-use browser refuse private, loopback, link-local and cloud-metadata addresses, check every redirect hop, and connect to the address they checked, so DNS rebinding cannot swap it. In the browser every request a page makes is checked. `allow_private_hosts=True` turns this off for trusted internal use.
- **File tools stay in the project.** Reads and writes, downloads and local PDFs included, are held to the project root and folders added with `add_dirs`.

## In code

Each default above is something you can see, and change, in a few lines.

### Approve tools by name

With the SDK API, a tool that no rule allows does not run. Reads and searches are free; everything else is named in `allowed_tools`, approved by a mode, or decided by `can_use_tool`.

```python
from shipit_agent.sdk import AgentOptions, PermissionResultAllow, PermissionResultDeny, query


async def can_use_tool(tool_name, tool_input, context):
    if tool_name == "bash" and "deploy" in tool_input.get("command", ""):
        return PermissionResultDeny(message="No deploys from the agent.")
    return PermissionResultAllow()


options = AgentOptions(
    model="claude-sonnet-5-5",
    allowed_tools=["Read", "Grep", "Bash(pytest *)"],  # pre-approved
    disallowed_tools=["Bash(rm *)", "Read(~/.ssh/**)"],  # refused in every mode
    can_use_tool=can_use_tool,                           # everything else
)

async for message in query(prompt="Run the tests and fix what fails.", options=options):
    print(message)
```

```text
Read(src/pricing.py)                 allowed: reads are free
Bash(pytest -q)                      allowed: matches Bash(pytest *)
Bash(rm -rf build)                   denied: Bash(rm *)
Bash(./deploy.sh)                    denied: No deploys from the agent.
```

### Keep URL tools on the public internet

`open_url`, `fetch_url`, `download_file`, `pdf` and the browser tools refuse private, loopback and cloud-metadata addresses, on every redirect. Opt out per tool, for an agent that works inside your own network.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools.open_url import OpenURLTool

llm = build_llm_from_env()

public_only = Agent(llm=llm, tools=[OpenURLTool()])  # the default
intranet = Agent(llm=llm, tools=[OpenURLTool(allow_private_hosts=True)])

result = public_only.run("Open http://169.254.169.254/latest/meta-data/ and summarise it.")
print(result.output)
```

```text
open_url(http://169.254.169.254/latest/meta-data/)
Error: refusing to fetch http://169.254.169.254/latest/meta-data/ — Host '169.254.169.254' resolves to a blocked address
I can't open that address: it is a cloud metadata endpoint, which is blocked.
```

### Run the server with a key

`shipit serve` is open only on `127.0.0.1`. Bound to any other address it needs a key and refuses to start without one; it checks the `Host`, `Origin` and `Content-Type` of every request.

```python
import os

from shipit_agent import Agent
from shipit_agent.cli.serve import AgentServer
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")
server = AgentServer(
    agent,
    api_key=os.environ["SHIPIT_API_KEY"],          # required off 127.0.0.1
    allowed_origins=["https://app.example.com"],   # the only browser origin accepted
)
server.serve_forever(host="0.0.0.0", port=8399)
```

```text
POST /v1/chat/completions  Authorization: Bearer <key>     200
POST /v1/chat/completions  (no key)                        401
POST /v1/chat/completions  Origin: https://evil.example    403
POST /v1/chat/completions  Content-Type: text/plain        415
```

### Redact tool output before the model sees it

An after-tool hook can replace a result. The replacement is what the model reads, not only what your UI shows.

```python
import re

from shipit_agent import Agent, AgentHooks
from shipit_agent.llms import build_llm_from_env

CARD = re.compile(r"\b(?:\d[ -]?){15}\d\b")
hooks = AgentHooks()


@hooks.on_after_tool
def hide_cards(name, result):
    return CARD.sub("[card hidden]", str(result.output))


agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".", hooks=hooks)
print(agent.run("Read data/orders.csv and list the customers.").output)
```

```text
Read(data/orders.csv)
id,customer,card
1,Ada,[card hidden]
2,Lin,[card hidden]
Two customers: Ada and Lin.
```

### Scrub traces before they leave

Tracing exporters send prompts, tool arguments and tool output. Wrap any trace store or exporter and it only ever receives scrubbed copies.

```python
from shipit_agent import Agent, InMemoryTraceStore
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tracing_exporters import RedactingTraceStore

traces = InMemoryTraceStore()
agent = Agent(
    llm=build_llm_from_env(),
    trace_store=RedactingTraceStore(traces, pii=True),  # secrets always; pii=True adds emails, phones, cards
)
agent.run("My key is sk-live-4f9a8b7c6d5e4f3a2b1c and my email is ada@example.com.")
```

```text
run_started    prompt: My key is [REDACTED:api-key] and my email is [REDACTED:email].
               run_id: fd6792f8-033f-41f3-a182-4455667f7453   (ids are kept)
run_completed  the run's own result and session are unchanged
```

## Principles

- Prefer explicit permission over silent access
- Keep tool scopes narrow and local by default
- Never transmit credentials through tool outputs
- Surface security-relevant actions through `interactive_request` events for human approval when needed
- Fail closed on untrusted input — validate at tool boundaries, not in the LLM
