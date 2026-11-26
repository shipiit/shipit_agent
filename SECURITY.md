# Security Policy

## Supported Versions

This project is early-stage. Security fixes are applied to the latest development version first.

## Reporting A Vulnerability

If you believe you have found a security issue, do not open a public issue with exploit details.

Please report it privately with:

- a short description of the issue
- affected files or components
- reproduction steps
- impact assessment
- any suggested mitigation

Until a dedicated security contact is published, use the repository maintainer contact channel or a private repository contact method.

## Scope

Areas that deserve extra care in this project:

- code execution
- MCP transports and remote tool calls
- browser automation
- file workspace access
- credentials used by model providers or search providers

## Secure Defaults

These hold without any configuration. Each can be changed in code; see
[docs/security.md](docs/security.md) for the examples.

- **SDK agents ask before acting.** With `query()` and `AgentClient`, reads and searches run freely; any other tool needs a rule in `allowed_tools`, a mode that approves it, a hook's `allow`, or a yes from `can_use_tool`.
- **URL and browser tools cannot reach your network.** `open_url`, `fetch_url`, `download_file`, `pdf`, `research_brief`, `playwright_browse` and the computer-use browser refuse private, loopback, link-local and cloud-metadata addresses on every redirect, and connect to the address they checked. `allow_private_hosts=True` turns this off per tool.
- **File tools stay in the project.** Reads, writes, downloads and local PDFs are held to the project root and folders you add.
- **`shipit serve` is open only on `127.0.0.1`.** Bound to any other address it refuses to start without a key, and it checks the `Host`, `Origin` and `Content-Type` of every request.
- **Redaction reaches the model.** A hook that replaces a tool's output replaces what the model reads, not only what is displayed.
- **Traces can be scrubbed before they leave.** `RedactingTraceStore` wraps any exporter and removes keys and, with `pii=True`, personal data, while keeping run and session ids intact.
- **MCP answers are checked.** A reply must match the request's id, listings are bounded, and `readOnlyHint` counts only as JSON `true`.

## Guidance For Users

- treat `CodeExecutionTool` as trusted-local execution, not a hardened sandbox
- use scoped API keys for provider-backed tools
- review MCP servers before attaching them
- do not expose this runtime to untrusted users without additional isolation
