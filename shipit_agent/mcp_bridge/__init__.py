"""Attaching MCP servers to a run without paying for the ones nobody calls.

Connecting to an MCP server is not free. A stdio server spawns a subprocess, runs
the ``initialize`` handshake and answers ``tools/list`` — all before the model has
decided to use a single one of its tools. With twenty connectors attached that is
twenty subprocesses and twenty round-trips on every run, most of them wasted. And
the tools that *are* discovered cost tokens forever after: twenty servers at ten
tools each is two hundred schemas in a prompt that is re-sent every turn.

So attachment happens in three separable stages, and a run pays only for the ones
it reaches:

1. **Describe** — read tool descriptors from the on-disk schema cache. No process
   spawned, no network. Enough to build the catalog and the tool definitions.
2. **Disclose** — put the cheap ones in the prompt and hold the rest behind
   ``tool_search`` (see :mod:`shipit_agent.discovery`), so a hundred available
   tools cost a handful of schemas until one is actually wanted.
3. **Connect** — spawn or dial only when a tool is called, and reuse the
   connection for the rest of the run.

Two smaller things this module fixes, both cheap and both currently missing:

**Server instructions reach the model.** The MCP spec's ``instructions`` field is
the server telling the model how to use it — "call ``list_projects`` before
``create_task``", "ids are ULIDs, not integers". It is read off the handshake and
then dropped on the floor, which means the model rediscovers those rules by
failing. Here it goes into the stable prefix, deduped and sorted by server.

**Schemas are prepared for the model that will see them.** MCP servers built on
Pydantic or FastMCP emit ``$defs`` and ``$ref`` for every nested argument model.
A strict OpenAI-*compatible* validator rejects those, so the failure is quiet and
selective: simple tools keep working, nested ones stop, and the model reads as
stupid rather than blocked.

The package: ``descriptors`` (naming, cached tool descriptors, lazily
connected tools) and ``bridge`` (:class:`MCPBridge`).
"""

from __future__ import annotations

from .bridge import MCPBridge
from .descriptors import (
    MCP_DELIMITER,
    AttachedServer,
    MCPToolDescriptor,
    namespaced,
    split_namespaced,
)

__all__ = [
    "MCPToolDescriptor",
    "AttachedServer",
    "MCPBridge",
    "namespaced",
    "split_namespaced",
    "MCP_DELIMITER",
]
