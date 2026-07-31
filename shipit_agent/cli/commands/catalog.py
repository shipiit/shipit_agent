"""Catalog listing commands: roles, mcp, tools."""

from __future__ import annotations

import argparse
import os
from typing import Any

from shipit_agent.cli import ui


def cmd_roles(_args: argparse.Namespace) -> int:
    from shipit_agent.agents import AgentRegistry

    registry = AgentRegistry.default()
    by_category: dict[str, list[str]] = {}
    for definition in registry.list_all():
        by_category.setdefault(definition.category or "Other", []).append(
            definition.id
        )
    for category in sorted(by_category):
        ui.section(category)
        for role_id in sorted(by_category[category]):
            ui.out(f"  {role_id}")
    ui.out(ui.style(
        f"\n{len(registry.list_all())} roles — "
        'use: shipit run --role finance-analyst "..."', "dim"))
    return 0


def cmd_mcp(_args: argparse.Namespace) -> int:
    from shipit_agent import list_mcp_catalog

    for entry in list_mcp_catalog():
        needs = (f"  (needs {', '.join(entry.required_env)})"
                 if entry.required_env else "")
        ui.out(f"{ui.style(entry.name, 'bold'):<24} {entry.description}"
               f"{ui.style(needs, 'warn')}")
    return 0


def cmd_tools(_args: argparse.Namespace) -> int:
    from shipit_agent.builtins import get_builtin_tools

    tools = get_builtin_tools(project_root=os.getcwd())
    for tool in sorted(tools, key=lambda t: t.name):
        desc = (getattr(tool, "description", "") or "").split("\n")[0][:70]
        ui.out(f"{ui.style(tool.name, 'bold'):<28} {desc}")
    ui.out(ui.style(f"\n{len(tools)} builtin tools", "dim"))
    return 0


def register(sub: Any) -> None:
    sub.add_parser("roles", help="List prebuilt sector specialists").set_defaults(
        fn=cmd_roles)
    sub.add_parser("mcp", help="List the prebuilt MCP catalog").set_defaults(
        fn=cmd_mcp)
    sub.add_parser("tools", help="List the builtin tool catalogue").set_defaults(
        fn=cmd_tools)
