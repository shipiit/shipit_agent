"""Benchmark tasks for code work and integrations: files, search, MCP, plugins."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from shipit_agent.sdk import (
    AssistantMessage,
    ResultMessage,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from .fixtures import BILLING_FUNCTIONS, SRC_PY_FILES, code_repo, plugin

FIXTURE_MCP = Path(__file__).resolve().parent.parent / "fixture_mcp_server.py"


@dataclass
class Run:
    """What one task produced: the workspace, the messages and their summary."""

    root: Path
    answer: str = ""
    result: Any = None
    tool_uses: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tool_errors: int = 0
    #: Each tool result's text and whether it failed, in order (for the trace).
    tool_results: list[tuple[str, bool]] = field(default_factory=list)
    #: Every ResultMessage, one per turn; a multi-turn task's cost is their sum.
    results: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def used(self, *names: str) -> bool:
        return any(name in names for name, _ in self.tool_uses)

    def record(self, message: Any) -> None:
        """Take in one streamed message: its calls, their results, the final result."""
        if isinstance(message, AssistantMessage):
            self.tool_uses += [(b.name, b.input) for b in message.content if isinstance(b, ToolUseBlock)]
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                failed = bool(getattr(block, "is_error", False))
                self.tool_errors += failed
                self.tool_results.append((str(getattr(block, "content", "")), failed))
        elif isinstance(message, ResultMessage):
            self.results.append(message)
            self.result, self.answer = message, message.result or ""


@dataclass
class Task:
    name: str
    feature: str
    prompt: str
    #: Extra AgentOptions for this task, given the workspace.
    options: Callable[[Path], dict[str, Any]]
    #: (passed, note) from the finished run.
    check: Callable[[Run], tuple[bool, str]]
    setup: Callable[[Path], None] = code_repo
    #: A task needing more than one query (a resume) runs itself.
    custom: Callable[..., Any] | None = None


def _tests_pass(run: Run) -> tuple[bool, str]:
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=run.root, capture_output=True, text=True, timeout=120)
    last = (done.stdout.strip().splitlines() or ["no output"])[-1]
    return done.returncode == 0, last


def _contains(*needles: str, tools: tuple[str, ...] = ()) -> Callable[[Run], tuple[bool, str]]:
    def check(run: Run) -> tuple[bool, str]:
        text = run.answer.lower()
        missing = [n for n in needles if n.lower() not in text]
        if missing:
            return False, f"answer lacks {missing}"
        if tools and not run.used(*tools):
            return False, f"never called {tools}"
        return True, "ok"

    return check


@tool("stock", "Units in stock for a SKU", {"sku": str}, annotations={"readOnlyHint": True})
def _stock(args: dict[str, Any]) -> dict[str, Any]:
    levels = {"SKU-7": 35, "SKU-9": 120}
    units = levels.get(str(args.get("sku")).upper())
    text = f"{units} units" if units is not None else "unknown SKU"
    return {"content": [{"type": "text", "text": text}]}


def _plugin_setup(root: Path) -> None:
    code_repo(root)
    plugin(root)


BASIC_TASKS = [
    Task("fix_failing_test", "files + bash",
         "The tests in this repo fail. Find the bug, fix it, and run the tests to confirm they pass.",
         lambda root: {}, _tests_pass),
    Task("find_definition", "search",
         "Which file under src/billing/ defines parse_invoice, and what currency does it use by default? "
         "Answer in one line: <path> <currency>.",
         lambda root: {"tools": ["Read", "Grep", "Glob"]},
         _contains("invoices.py", "eur")),
    Task("mcp_in_process", "MCP (in-process)",
         "How many units of SKU-7 are in stock, and is that enough for an order of 40? Answer with the number and yes or no.",
         lambda root: {"tools": [], "mcp_servers": {"inventory": create_sdk_mcp_server("inventory", tools=[_stock])}},
         _contains("35", "no", tools=("inventory__stock",))),
    Task("mcp_stdio", "MCP (stdio server)",
         "Use the case archive to retrieve CASE-1 and give its evidence code and amount.",
         lambda root: {"tools": [], "mcp_servers": {"cases": {"type": "stdio", "command": sys.executable,
                                                              "args": [str(FIXTURE_MCP)]}}},
         _contains("evidence-15838", "117")),
    Task("plugin_command", "plugin command",
         "/bench:lines data.txt",
         lambda root: {"tools": ["Read", "Bash"], "plugins": [{"type": "local", "path": "plugins/bench"}]},
         _contains("23"), setup=_plugin_setup),
    Task("plugin_skill", "plugin skill",
         "/bench:greeting Ada",
         lambda root: {"tools": [], "plugins": [{"type": "local", "path": "plugins/bench"}]},
         _contains("ahoy, ada!"), setup=_plugin_setup),
]

#: Facts the control tasks check against.
FACTS = {"src_py_files": SRC_PY_FILES, "billing_functions": BILLING_FUNCTIONS}
