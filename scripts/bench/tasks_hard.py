"""Harder benchmark tasks: memory across turns, a bug that crosses modules,
recovering from a tool error, and finding one line in a large file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shipit_agent.sdk import AgentClient, create_sdk_mcp_server, tool

from .tasks_basic import Run, Task, _contains, _tests_pass

PRICING = '''def apply_discount(price, percent):
    """The price after taking *percent* off."""
    return price * percent / 100
'''

CART = '''from shop.pricing import apply_discount


def cart_total(items, discount_percent=0):
    subtotal = sum(price * quantity for price, quantity in items)
    return round(apply_discount(subtotal, discount_percent), 2)
'''

CART_TESTS = '''from shop.cart import cart_total


def test_no_discount():
    assert cart_total([(10.0, 2), (5.0, 1)]) == 25.0


def test_ten_percent_off():
    assert cart_total([(10.0, 2), (5.0, 1)], discount_percent=10) == 22.5
'''

#: The log line the large-file task must find, and where it is.
NEEDLE_LINE = 3817
NEEDLE = "ERROR code=E417 payment gateway timed out"


def shop_repo(root: Path) -> None:
    """A failing test in cart that is caused by a bug in pricing."""
    (root / "shop").mkdir()
    (root / "shop" / "__init__.py").write_text("")
    (root / "shop" / "pricing.py").write_text(PRICING)
    (root / "shop" / "cart.py").write_text(CART)
    (root / "test_cart.py").write_text(CART_TESTS)


def big_log(root: Path) -> None:
    lines = [f"2026-11-06T10:{i // 60 % 60:02d}:{i % 60:02d} INFO request {i} ok" for i in range(1, 6001)]
    lines[NEEDLE_LINE - 1] = f"2026-11-06T11:03:37 {NEEDLE}"
    (root / "service.log").write_text("\n".join(lines) + "\n")


@tool("order_status", "Status of an order. The id looks like ORD-<number>.", {"order_id": str},
      annotations={"readOnlyHint": True})
def _order_status(args: dict[str, Any]) -> dict[str, Any]:
    order_id = str(args.get("order_id", "")).strip()
    if not order_id.upper().startswith("ORD-"):
        return {"content": [{"type": "text", "text": f"Invalid id {order_id!r}: ids look like ORD-42."}],
                "is_error": True}
    status = {"ORD-42": "shipped on 2026-11-03, tracking ZX-9917"}.get(order_id.upper(), "not found")
    return {"content": [{"type": "text", "text": status}]}


async def _two_turns(task: Task, run_query: Any, root: Path) -> Run:
    """One client, two turns: the second can only be answered from the first."""
    run = Run(root=root)
    async with AgentClient(run_query.options({"tools": ["Read"]}, root)) as client:
        await client.query("Read src/util.py. Just tell me the name of the function it defines.")
        async for message in client.receive_response():
            run.record(message)
        first_calls = len(run.tool_uses)
        await client.query("Without reading anything again: what does that function do to spaces?")
        async for message in client.receive_response():
            run.record(message)
    run.extra["second_turn_calls"] = len(run.tool_uses) - first_calls
    return run


def _remembered(run: Run) -> tuple[bool, str]:
    text = run.answer.lower()
    if not any(word in text for word in ("hyphen", "dash", "'-'", '"-"', "`-`")):
        return False, f"second answer lacks the hyphen: {run.answer[:60]!r}"
    if run.extra.get("second_turn_calls"):
        return False, "read the file again instead of remembering"
    return True, "ok"


def _recovered(run: Run) -> tuple[bool, str]:
    passed, note = _contains("shipped", "zx-9917", tools=("orders__order_status",))(run)
    return passed, (f"{note}; {run.tool_errors} tool error(s) on the way" if passed else note)


HARD_TASKS = [
    Task("multi_turn_memory", "multi-turn client",
         "(two turns through AgentClient)", lambda root: {}, _remembered, custom=_two_turns),
    Task("cross_module_bug", "files + bash",
         "test_cart.py fails. Find the root cause, fix it where it lives, and run the tests to confirm.",
         lambda root: {}, _tests_pass, setup=shop_repo),
    Task("tool_error_recovery", "MCP error recovery",
         "What is the status of order 42?",
         lambda root: {"tools": [], "mcp_servers": {"orders": create_sdk_mcp_server("orders", tools=[_order_status])}},
         _recovered),
    Task("needle_in_log", "search a large file",
         "service.log has 6,000 lines. Find the ERROR line and give its line number and error code.",
         lambda root: {"tools": ["Read", "Grep", "Bash"]},
         _contains(str(NEEDLE_LINE), "e417"), setup=big_log),
]
