"""Discovering a remote MCP server's tools, with an optional on-disk schema cache."""

from __future__ import annotations

import hashlib
from typing import Any

from .tools import (
    MCPRemoteTool,
    MCPTool,
    _namespaced_mcp_tool_name,
    _sanitize_tool_name,
)
from .transport import _MAX_TOOL_NAME_LENGTH, MCPError


class ToolDiscoveryMixin:
    """Discovering a remote MCP server's tools, with an optional on-disk schema cache."""

    def _cache_fingerprint(self) -> str:
        # Computed *before* initialize() so protocol negotiation can't shift the
        # key between the load (cold) and save (post-handshake) within a run.
        from shipit_agent import mcp_schema_cache

        return mcp_schema_cache.fingerprint(
            name=self.name,
            identity=mcp_schema_cache.transport_identity(self.transport),
            protocol_version=self.protocol_version,
            allowed=self.allowed_tools,
            blocked=self.blocked_tools,
            include_server_in_tool_names=self.include_server_in_tool_names,
            env=getattr(self.transport, "env", None),
        )

    def _descriptor(
        self, item: dict[str, Any], exposed_name: str, remote_name: str
    ) -> dict[str, Any]:
        """A resolved, JSON-serialisable tool descriptor — the cache unit."""
        return {
            "name": exposed_name,
            "remote_name": remote_name,
            "description": str(item.get("description", "")),
            "input_schema": dict(
                item.get("inputSchema")
                or {"type": "object", "properties": {}, "required": []}
            ),
            "output_schema": dict(item.get("outputSchema") or {}),
            "title": str(item.get("title", "")),
            "annotations": dict(item.get("annotations") or {}),
            "execution": dict(item.get("execution") or {}),
        }

    def _tool_from_descriptor(self, descriptor: dict[str, Any]) -> MCPRemoteTool:
        """Build a live tool from a descriptor — the one place both the live and
        the cache paths construct an :class:`MCPRemoteTool`, so they can't drift."""
        return MCPRemoteTool(
            server_name=self.name,
            transport=self.transport,
            name=str(descriptor["name"]),
            remote_name=str(descriptor.get("remote_name", "")),
            description=str(descriptor.get("description", "")),
            input_schema=dict(
                descriptor.get("input_schema")
                or {"type": "object", "properties": {}, "required": []}
            ),
            output_schema=dict(descriptor.get("output_schema") or {}),
            title=str(descriptor.get("title", "")),
            annotations=dict(descriptor.get("annotations") or {}),
            metadata={
                "server": self.name,
                "remote_name": str(descriptor.get("remote_name", "")),
                "title": str(descriptor.get("title", "")),
                "annotations": dict(descriptor.get("annotations") or {}),
                "execution": dict(descriptor.get("execution") or {}),
            },
            tool_meta_resolver=self.tool_meta_resolver,
            ensure_ready=self._ensure_ready,
        )

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        if self._discovered:
            if self._lazy_pending:
                # Built from cache, process not yet spawned. Every-turn
                # re-discovery must NOT initialize here — that would defeat the
                # laziness. Return the cached tools with zero transport traffic;
                # the first tool call spawns and handshakes via ensure_ready.
                return list(self.tools)
            # A prior agent turn may have closed the transport. Persistent
            # transports can reopen themselves, but the new MCP session must
            # complete the protocol handshake before cached tools are reused.
            self.initialize()
            return list(self.tools)
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")

        # Warm start: rebuild from the on-disk schema cache without spawning.
        # Skipped when a callable tool_filter is set — it can't be fingerprinted,
        # so a cached schema could include tools the filter would now exclude.
        fingerprint: str | None = None
        if self.cache and self.tool_filter is None:
            from shipit_agent import mcp_schema_cache

            fingerprint = self._cache_fingerprint()
            cached = mcp_schema_cache.load(self.name, fingerprint, ttl=self.cache_ttl)
            if cached is not None:
                self.tools = [self._tool_from_descriptor(d) for d in cached]
                self._discovered = True
                self._lazy_pending = True
                return list(self.tools)

        # Cold path: live discovery (spawn + handshake + tools/list).
        try:
            self.initialize()
            tool_items = self._paginated_items("tools/list", "tools")
            descriptors: list[dict[str, Any]] = []
            exposed_names: set[str] = set()
            for item in tool_items:
                if not self._tool_allowed(item):
                    continue
                remote_name = str(item["name"])
                # Sanitization is unconditional — only the server prefix is
                # opt-in. The raw name still goes on the wire via
                # ``remote_name``; providers only ever see the safe one.
                exposed_name = (
                    _namespaced_mcp_tool_name(self.name, remote_name)
                    if self.include_server_in_tool_names
                    else _sanitize_tool_name(remote_name)
                )
                if exposed_name in exposed_names:
                    digest = hashlib.sha256(remote_name.encode("utf-8")).hexdigest()[:8]
                    exposed_name = (
                        f"{exposed_name[: _MAX_TOOL_NAME_LENGTH - 9]}_{digest}"
                    )
                exposed_names.add(exposed_name)
                descriptors.append(self._descriptor(item, exposed_name, remote_name))
            resolved_tools: list[MCPTool | MCPRemoteTool] = [
                self._tool_from_descriptor(descriptor) for descriptor in descriptors
            ]
        except Exception:
            # Discovery opened the connection/subprocess; if it fails we must
            # close the transport so we don't leak a live process or socket.
            self.close()
            raise
        self.tools = resolved_tools
        self._discovered = True
        self._lazy_pending = False
        # Persist for the next warm start (best-effort; never raises). Uses the
        # pre-initialize fingerprint so it matches what a future load computes.
        if fingerprint is not None:
            from shipit_agent import mcp_schema_cache

            mcp_schema_cache.save(self.name, fingerprint, descriptors)
        return list(self.tools)
