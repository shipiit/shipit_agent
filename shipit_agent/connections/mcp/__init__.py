"""MCP servers as records, so adding a connection is configuration.

``connections/models.py`` and ``registry.py`` already model a *connection* — its
auth kind, its state, whether the user has connected it. What they do not carry
is how to reach an MCP server: transport, command or URL, which environment
variable holds the token. That is what this adds, alongside rather than instead.

Every connector written as a class is a release cycle between "we need Linear"
and having Linear. So a connector is data. It comes from YAML, a dict, or the
shipped catalog, and all three are the same shape:

```yaml
connections:
  jira:
    transport: sse
    url: https://mcp.atlassian.com/v1/sse
    auth: {kind: bearer, env: JIRA_MCP_TOKEN}
  local-fs:
    use: filesystem          # a catalog template, then override anything
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./src"]
```

Two decisions worth stating:

**Secrets are named, never stored.** A record holds the *name* of an environment
variable. A config file that leaks then leaks a variable name, which is not a
secret. Resolution happens at connect time, and a missing variable is a named,
fixable condition rather than a 401 twenty seconds later.

**Unreachable is a state, not an exception.** ``check()`` returns a verdict for
every connector, so a preflight shows the whole picture at once. Discovering
three missing tokens one failed connection at a time is three times the work.

The package: ``connector`` (one connector), ``catalog`` (the built-ins),
``registry`` (the set a run uses).
"""

from __future__ import annotations

from .catalog import MCP_CATALOG
from .connector import MCPAuth, MCPAuthKind, MCPConnector, MCPConnectorStatus, Transport
from .registry import MCPConnectorRegistry

__all__ = [
    "Transport",
    "MCPAuthKind",
    "MCPAuth",
    "MCPConnector",
    "MCPConnectorStatus",
    "MCPConnectorRegistry",
    "MCP_CATALOG",
]
