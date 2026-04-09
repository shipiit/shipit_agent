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

## Principles

- Prefer explicit permission over silent access
- Keep tool scopes narrow and local by default
- Never transmit credentials through tool outputs
- Surface security-relevant actions through `interactive_request` events for human approval when needed
- Fail closed on untrusted input — validate at tool boundaries, not in the LLM
