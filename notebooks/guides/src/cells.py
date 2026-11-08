"""Helpers for guide sources: md() and code() cells, dedented."""

from __future__ import annotations

from textwrap import dedent


def md(text: str) -> tuple[str, str]:
    return ("md", dedent(text).strip())


def code(text: str) -> tuple[str, str]:
    return ("code", dedent(text).strip())
