"""Smoke tests: every new example script runs offline without error."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name",
    [
        "13_parallel_tools",
        "14_cost_budget",
        "15_multi_turn_memory",
        "17_secure_tools",
        "18_verifier_guard",
    ],
)
def test_sync_example_runs(name: str, capsys) -> None:
    module = _load(name)
    module.main()  # must not raise
    out = capsys.readouterr().out
    assert out.strip()  # produced some output


def test_async_example_runs(capsys) -> None:
    module = _load("16_async_agent")
    asyncio.run(module.main())
    out = capsys.readouterr().out
    assert "run_completed" in out or "tool_completed" in out
