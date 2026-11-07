"""Long benchmark tasks: enough reads and edits that the history piles up.

The short tasks finish in a few turns, so what each turn re-sends barely
matters. These take many turns, which is where keeping old tool results in
the conversation, or clearing them, shows in the tokens.
"""

from __future__ import annotations

import re
from pathlib import Path

from .tasks_basic import Run, Task, _tests_pass

MODULES = ["orders", "invoices", "refunds", "payouts", "ledger", "reports", "alerts", "exports"]


def _module(name: str) -> str:
    # Each module is long enough that reading it costs real tokens.
    helpers = "\n\n".join(
        f'def {name}_helper_{n}(value):\n    """Helper {n} for {name}."""\n    return value * {n + 1}'
        for n in range(40)
    )
    return (f'"""The {name} module."""\n\nfrom ledgerlib.money import to_cents_amount\n\n\n'
            f'def {name}_total(amounts):\n    return sum(to_cents_amount(a) for a in amounts)\n\n\n'
            f'{helpers}\n')


def rename_repo(root: Path) -> None:
    """A package where `to_cents_amount` is used by eight modules and their tests."""
    pkg = root / "ledgerlib"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "money.py").write_text('"""Money helpers."""\n\n\ndef to_cents_amount(value):\n'
                                  '    return round(float(value) * 100)\n')
    for name in MODULES:
        (pkg / f"{name}.py").write_text(_module(name))
        (root / f"test_{name}.py").write_text(
            f"from ledgerlib.{name} import {name}_total\nfrom ledgerlib.money import to_cents_amount\n\n\n"
            f"def test_{name}_total():\n    assert {name}_total(['1.50', 2]) == 350\n\n\n"
            f"def test_cents():\n    assert to_cents_amount('0.10') == 10\n")


def _renamed(run: Run) -> tuple[bool, str]:
    passed, note = _tests_pass(run)
    if not passed:
        return False, note
    left = [p.name for p in run.root.rglob("*.py") if re.search(r"\bto_cents_amount\b", p.read_text())]
    if left:
        return False, f"old name still in {sorted(left)}"
    if not any(re.search(r"\bto_cents\b", p.read_text()) for p in run.root.rglob("*.py")):
        return False, "new name not found"
    return True, note


COUPON_TESTS = '''from shop.cart import cart_total
from shop.coupons import coupon_percent


def test_known_coupons():
    assert coupon_percent("SAVE10") == 10
    assert coupon_percent("save25") == 25


def test_unknown_coupon_is_zero():
    assert coupon_percent("NOPE") == 0


def test_cart_with_coupon():
    assert cart_total([(10.0, 2), (5.0, 1)], coupon="SAVE10") == 22.5


def test_coupon_and_discount_do_not_stack_past_50():
    assert cart_total([(100.0, 1)], discount_percent=30, coupon="SAVE25") == 50.0
'''

COUPON_SPEC = '''# Coupons

- Codes are case-insensitive. SAVE10 takes 10% off, SAVE25 takes 25% off.
  Any other code takes nothing off.
- `cart_total(items, discount_percent=0, coupon=None)` adds the coupon's
  percent to the discount, but the total taken off is never more than 50%.
- Put the codes in a new module, `shop/coupons.py`, with `coupon_percent(code)`.
'''


def feature_repo(root: Path) -> None:
    """The shop from cross_module_bug, fixed, plus failing coupon tests and a spec."""
    from .tasks_hard import PRICING, shop_repo

    shop_repo(root)
    (root / "shop" / "pricing.py").write_text(PRICING.replace("price * percent / 100", "price * (1 - percent / 100)"))
    (root / "test_coupons.py").write_text(COUPON_TESTS)
    (root / "COUPONS.md").write_text(COUPON_SPEC)


LONG_TASKS = [
    Task("rename_across_modules", "long: refactor",
         "Rename the function `to_cents_amount` to `to_cents` everywhere in this repository, "
         "including every use and test, then run the tests to confirm they pass.",
         lambda root: {"max_turns": 40}, _renamed, setup=rename_repo),
    Task("add_feature", "long: feature",
         "Implement the coupon feature described in COUPONS.md so that test_coupons.py passes, "
         "without breaking the other tests. Run the tests to confirm.",
         lambda root: {"max_turns": 40}, _tests_pass, setup=feature_repo),
]
