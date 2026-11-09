"""docs/reference/api.md lists every exported name and is up to date."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import shipit_agent

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("build_api_reference", ROOT / "scripts" / "build_api_reference.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_the_page_is_current() -> None:
    import difflib

    saved, built = builder.OUT.read_text(encoding="utf-8"), builder.build()
    diff = "".join(difflib.unified_diff(saved.splitlines(True), built.splitlines(True), n=0))
    assert not diff, f"run python scripts/build_api_reference.py\n{diff[:1500]}"


def test_every_export_has_a_row() -> None:
    page = builder.OUT.read_text(encoding="utf-8")
    missing = [name for name in shipit_agent.__all__ if f"| `{name}` |" not in page]
    assert missing == []


def test_the_page_is_in_the_nav() -> None:
    assert "reference/api.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_kinds_and_summaries() -> None:
    assert builder._kind(shipit_agent.Agent) == "class"
    assert builder._kind(len) == "function"
    assert builder._kind(42) == "constant"
    assert builder._summary(42) == "A `int`."
    assert builder._summary(type("Bare", (), {})) == "—"
    assert builder._module("x", 42) == "shipit_agent"


def test_type_aliases_read_the_same_on_every_python() -> None:
    from typing import Optional, Union

    for alias in (int | str, Union[int, str], Optional[int], list[int]):
        assert builder._kind(alias) == "type alias"
        assert builder._summary(alias) == "A type alias."
