"""Small, synthetic workspaces for the benchmark tasks. No network, no real data."""

from __future__ import annotations

import json
from pathlib import Path

BUGGY_CALC = '''def add(a, b):
    """Return the sum of a and b."""
    return a - b


def multiply(a, b):
    return a * b
'''

CALC_TESTS = '''from calc import add, multiply


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_multiply():
    assert multiply(4, 5) == 20
'''

BILLING = '''"""Invoices for the billing service."""

DEFAULT_CURRENCY = "EUR"


def parse_invoice(text, currency=DEFAULT_CURRENCY):
    number, amount = text.split(":")
    return {"number": number.strip(), "amount": float(amount), "currency": currency}


def invoice_total(invoices):
    return sum(item["amount"] for item in invoices)


def format_invoice(invoice):
    return f"{invoice['number']}: {invoice['amount']:.2f} {invoice['currency']}"
'''

#: Python files under src/ in the repo fixture, and functions in billing.py.
SRC_PY_FILES = 4
BILLING_FUNCTIONS = 3


def code_repo(root: Path) -> None:
    """A tiny project: a calculator with a failing test, and a billing package."""
    (root / "calc.py").write_text(BUGGY_CALC)
    (root / "test_calc.py").write_text(CALC_TESTS)
    src = root / "src"
    (src / "billing").mkdir(parents=True)
    (src / "billing" / "__init__.py").write_text("")
    (src / "billing" / "invoices.py").write_text(BILLING)
    (src / "billing.py").write_text(BILLING)
    (src / "util.py").write_text("def slug(text):\n    return text.lower().replace(' ', '-')\n")
    (root / "build").mkdir()
    (root / "build" / "app.bin").write_text("binary")
    (root / "data.txt").write_text("".join(f"row {i}\n" for i in range(1, 24)))


def plugin(root: Path) -> Path:
    """A plugin named 'bench' with one command and one skill."""
    folder = root / "plugins" / "bench"
    (folder / "commands").mkdir(parents=True)
    (folder / "commands" / "lines.md").write_text(
        "---\ndescription: Count lines\n---\nCount the lines in the file $1 and reply with only the number.\n")
    (folder / "skills" / "greeting").mkdir(parents=True)
    (folder / "skills" / "greeting" / "SKILL.md").write_text(
        "---\nname: greeting\ndescription: Greet a person in the house style.\n---\n"
        "Greet the person named in the request with exactly: Ahoy, <name>! Then stop.\n")
    (folder / ".claude-plugin").mkdir()
    (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "bench"}))
    return folder
