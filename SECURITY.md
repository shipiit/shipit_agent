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

## Guidance For Users

- treat `CodeExecutionTool` as trusted-local execution, not a hardened sandbox
- use scoped API keys for provider-backed tools
- review MCP servers before attaching them
- do not expose this runtime to untrusted users without additional isolation
