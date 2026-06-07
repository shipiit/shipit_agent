"""Regression tests for the second-pass gap fixes:

- SEC-5  FileCredentialStore: atomic write + 0600 perms + plaintext warning
- grep   GrepSearchTool: configurable subprocess timeout
- coord  ShipCoordinator: timeout_seconds actually preempts a slow task
- MEM-1  CostTracker: unknown model under budget warns (does NOT crash)
"""

from __future__ import annotations

import os
import time

from shipit_agent import Budget, CostTracker
from shipit_agent.integrations.credentials import (
    CredentialRecord,
    FileCredentialStore,
)
from shipit_agent.tools.grep_search.grep_search_tool import GrepSearchTool


# --------------------------------------------------------------------------
# SEC-5 — credential store hardening
# --------------------------------------------------------------------------


class TestCredentialStoreHardening:
    def test_round_trips_secrets(self, tmp_path) -> None:
        store = FileCredentialStore(tmp_path / "creds.json", warn=False)
        store.set(CredentialRecord(key="k", provider="p", secrets={"token": "s3cr3t"}))
        loaded = store.get("k")
        assert loaded is not None
        assert loaded.secrets["token"] == "s3cr3t"

    def test_file_permissions_owner_only_on_posix(self, tmp_path) -> None:
        if os.name != "posix":
            return
        path = tmp_path / "creds.json"
        store = FileCredentialStore(path, warn=False)
        store.set(CredentialRecord(key="k", provider="p", secrets={"t": "x"}))
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600

    def test_atomic_write_leaves_no_tmp(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        store = FileCredentialStore(path, warn=False)
        store.set(CredentialRecord(key="k", provider="p", secrets={"t": "x"}))
        assert not (tmp_path / "creds.json.tmp").exists()

    def test_warns_about_plaintext(self, tmp_path, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            FileCredentialStore(tmp_path / "creds.json")
        assert any("plaintext" in r.message.lower() for r in caplog.records)


# --------------------------------------------------------------------------
# grep — configurable timeout
# --------------------------------------------------------------------------


class TestGrepTimeout:
    def test_timeout_attribute_default(self) -> None:
        tool = GrepSearchTool(root_dir="/tmp")
        assert tool.timeout_seconds == 30.0

    def test_timeout_attribute_configurable(self) -> None:
        tool = GrepSearchTool(root_dir="/tmp", timeout_seconds=5)
        assert tool.timeout_seconds == 5


# --------------------------------------------------------------------------
# coord — timeout actually preempts
# --------------------------------------------------------------------------


class TestCoordinatorTimeoutPreempts:
    def test_slow_task_times_out_quickly(self) -> None:
        from shipit_agent.deep.ship_crew.agent import ShipAgent
        from shipit_agent.deep.ship_crew.coordinator import ShipCoordinator
        from shipit_agent.deep.ship_crew.errors import TaskTimeoutError
        from shipit_agent.deep.ship_crew.task import ShipTask

        class _SlowAgent:
            def run(self, prompt: str):
                time.sleep(5)  # far longer than the task's 1s limit

        ship_agent = ShipAgent(name="slow", agent=_SlowAgent())
        coordinator = ShipCoordinator(
            llm=None,
            agents={"slow": ship_agent},
            tasks=[],
        )
        task = ShipTask(
            name="t",
            description="do it",
            agent="slow",
            timeout_seconds=1,
            max_retries=1,
        )

        started = time.monotonic()
        raised = False
        try:
            coordinator._execute_task(task, {}, {"slow": ship_agent})
        except TaskTimeoutError:
            raised = True
        elapsed = time.monotonic() - started

        assert raised, "expected TaskTimeoutError"
        # Must give up at ~1s (the limit), NOT wait the full 5s sleep.
        assert elapsed < 3.0, f"timeout did not preempt: waited {elapsed:.1f}s"


# --------------------------------------------------------------------------
# MEM-1 — corrected semantics: warn (default) does not crash
# --------------------------------------------------------------------------


class TestUnknownModelDoesNotCrash:
    def test_unknown_model_under_budget_warns_not_raises(self) -> None:
        tracker = CostTracker(budget=Budget(max_dollars=10.0))
        # Must NOT raise for a brand-new / custom model id.
        rec = tracker.record_call("brand-new-model-x", 1000, 1000)
        assert rec.cost_usd == 0.0
        assert tracker.has_unknown_pricing is True
