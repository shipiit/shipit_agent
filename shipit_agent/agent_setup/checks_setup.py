"""AgentDoctor checks for the LLM, MCP servers, stores and connectors."""

from __future__ import annotations

from typing import Any

from .doctor_types import DoctorCheck


class _SetupChecks:
    """AgentDoctor checks for the LLM, MCP servers, stores and connectors."""

    def _check_llm(self, llm: Any) -> DoctorCheck:
        provider, details = self._provider_details(llm)
        missing = list(details.pop("missing", []))
        if provider == "shipit":
            return DoctorCheck(
                name="llm_provider",
                status="pass",
                message="ShipitLLM is configured for local development and smoke tests.",
                details=details,
            )
        if missing:
            return DoctorCheck(
                name="llm_provider",
                status="fail",
                message=f"{provider} configuration is missing required environment variables.",
                details={**details, "missing": ", ".join(missing)},
            )
        return DoctorCheck(
            name="llm_provider",
            status="pass",
            message=f"{provider} configuration looks ready.",
            details=details,
        )

    def _check_mcps(self, mcps: list[Any]) -> DoctorCheck:
        if not mcps:
            return DoctorCheck(
                name="mcps",
                status="warn",
                message="No MCP servers are attached.",
                details={"mcp_count": 0},
            )
        names = [getattr(mcp, "name", mcp.__class__.__name__) for mcp in mcps]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            return DoctorCheck(
                name="mcps",
                status="fail",
                message="MCP server names must be unique.",
                details={
                    "mcp_count": len(names),
                    "duplicates": ", ".join(duplicates),
                },
            )
        return DoctorCheck(
            name="mcps",
            status="pass",
            message="MCP servers are attached.",
            details={"mcp_count": len(names), "servers": ", ".join(names)},
        )

    def _check_stores(self, agent: Any) -> DoctorCheck:
        details = {
            "memory_store": agent.memory_store.__class__.__name__
            if getattr(agent, "memory_store", None)
            else "None",
            "session_store": agent.session_store.__class__.__name__
            if getattr(agent, "session_store", None)
            else "None",
            "trace_store": agent.trace_store.__class__.__name__
            if getattr(agent, "trace_store", None)
            else "None",
            "session_id": getattr(agent, "session_id", None) or "unset",
            "trace_id": getattr(agent, "trace_id", None) or "unset",
        }
        if not getattr(agent, "memory_store", None) or not getattr(
            agent, "session_store", None
        ):
            return DoctorCheck(
                name="stores",
                status="warn",
                message="Persistent stores are only partially configured.",
                details=details,
            )
        return DoctorCheck(
            name="stores",
            status="pass",
            message="Memory, session, and trace stores are configured.",
            details=details,
        )

    def _check_connectors(self, tools: list[Any], credential_store: Any) -> DoctorCheck:
        connector_tools = [tool for tool in tools if hasattr(tool, "credential_key")]
        if not connector_tools:
            return DoctorCheck(
                name="connectors",
                status="pass",
                message="No connector tools require credentials.",
                details={"connector_count": 0},
            )
        if credential_store is None:
            return DoctorCheck(
                name="connectors",
                status="warn",
                message="Connector tools are attached but no credential store is configured.",
                details={"connector_count": len(connector_tools)},
            )
        from shipit_agent.connections import ConnectionRegistry

        registry = ConnectionRegistry(
            credential_store=credential_store,
            tools=connector_tools,
        )
        connections = {connection.id: connection for connection in registry.all()}
        unavailable: list[str] = []
        connected: list[str] = []
        for tool in connector_tools:
            credential_key = getattr(tool, "credential_key", "")
            provider = getattr(
                tool, "provider", credential_key or getattr(tool, "name", "connector")
            )
            connection = connections.get(credential_key)
            if connection is not None and connection.usable:
                connected.append(f"{provider}:{credential_key}")
            else:
                state = connection.state.value if connection is not None else "missing"
                unavailable.append(f"{provider}:{credential_key}({state})")
        if unavailable:
            return DoctorCheck(
                name="connectors",
                status="warn",
                message="Some connector tools are not ready to use.",
                details={
                    "connector_count": len(connector_tools),
                    "connected": ", ".join(connected) or "none",
                    "unavailable": ", ".join(unavailable),
                },
            )
        return DoctorCheck(
            name="connectors",
            status="pass",
            message="All connector tools have credential records.",
            details={
                "connector_count": len(connector_tools),
                "connected": ", ".join(connected) or "none",
            },
        )
