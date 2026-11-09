"""Every Python example in the published docs parses, and its shipit imports resolve.

Docs drift silently: a renamed class keeps working in the page until a
reader copies it. Blocks that are deliberately not Python (a sketch with
`...` placeholders still parses) need no marker; a block that must not be
checked starts with `# docs: no-check` and says why on the same line.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,})(?:python|py)\s*\n(?P<body>.*?)^(?P=indent)(?P=fence)\s*$", re.M | re.S)


def _nav_pages() -> list[str]:
    text = (ROOT / "mkdocs.yml").read_text()
    text = re.sub(r"!!python/name:\S+", "''", text).replace("!ENV", "")
    pages: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            pages.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(yaml.safe_load(text)["nav"])
    return sorted(set(pages))


def _blocks() -> list[tuple[str, int, str]]:
    found = []
    for page in _nav_pages():
        text = (DOCS / page).read_text()
        for match in FENCE.finditer(text):
            indent = match.group("indent")
            body = "\n".join(line[len(indent):] for line in match.group("body").splitlines())
            if body.lstrip().startswith("# docs: no-check"):
                continue
            line = text[: match.start()].count("\n") + 1
            found.append((page, line, body))
    return found


BLOCKS = _blocks()


@pytest.mark.parametrize("page, line, body", BLOCKS, ids=[f"{p}:{n}" for p, n, _ in BLOCKS])
def test_example_parses_and_its_imports_resolve(page: str, line: int, body: str) -> None:
    tree = ast.parse(body)  # a syntax error fails here, naming page:line
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("shipit_agent") and node.level == 0:
            module = importlib.import_module(node.module)
            missing += [f"{node.module}.{a.name}" for a in node.names
                        if a.name != "*" and not hasattr(module, a.name)
                        and importlib.util.find_spec(f"{node.module}.{a.name}") is None]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("shipit_agent"):
                    importlib.import_module(alias.name)
    assert not missing, f"{page}:{line} imports names that do not exist: {missing}"
    bad = _unknown_keywords(tree)
    assert not bad, f"{page}:{line} passes keywords these do not take: {bad}"


def _imported(tree: ast.AST) -> dict[str, object]:
    names: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("shipit_agent") and node.level == 0:
            module = importlib.import_module(node.module)
            for alias in node.names:
                if hasattr(module, alias.name):
                    names[alias.asname or alias.name] = getattr(module, alias.name)
    return names


def _accepts(target: object) -> tuple[set[str], bool] | None:
    """The keyword names *target* takes, and whether it takes **kwargs."""
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return None
    names = {p.name for p in signature.parameters.values() if p.kind is not p.VAR_POSITIONAL}
    return names, any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())


def _unknown_keywords(tree: ast.AST) -> list[str]:
    """Keyword arguments in calls to imported shipit names (and their classmethods) that no signature accepts."""
    names = _imported(tree)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = None
        if isinstance(node.func, ast.Name) and node.func.id in names:
            target, label = names[node.func.id], node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in names:
            owner = names[node.func.value.id]
            if inspect.isclass(owner) and hasattr(owner, node.func.attr):
                target, label = getattr(owner, node.func.attr), f"{node.func.value.id}.{node.func.attr}"
        if target is None:
            continue
        accepted = _accepts(target)
        if accepted is None or accepted[1]:
            continue
        bad += [f"{label}({kw.arg}=)" for kw in node.keywords if kw.arg and kw.arg not in accepted[0]]
    return bad
