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
- **URL tools cannot reach your network.** `open_url`, `fetch_url`, `download_file`, `pdf` and `research_brief` refuse private, loopback, link-local and cloud-metadata addresses, check every redirect hop, and connect to the address they checked, so DNS rebinding cannot swap it. In the browser every request a page makes is checked. `allow_private_hosts=True` turns this off for trusted internal use.
- **File tools stay in the project.** Reads and writes, downloads and local PDFs included, are held to the project root and folders added with `add_dirs`.

## Principles

- Prefer explicit permission over silent access
- Keep tool scopes narrow and local by default
- Never transmit credentials through tool outputs
- Surface security-relevant actions through `interactive_request` events for human approval when needed
- Fail closed on untrusted input — validate at tool boundaries, not in the LLM
