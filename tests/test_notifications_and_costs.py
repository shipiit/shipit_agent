"""Comprehensive tests for the notifications and cost-tracking subsystems.

Covers:
    - shipit_agent.notifications.base
    - shipit_agent.notifications.templates
    - shipit_agent.notifications.slack
    - shipit_agent.notifications.discord
    - shipit_agent.notifications.telegram
    - shipit_agent.notifications.manager
    - shipit_agent.costs.pricing
    - shipit_agent.costs.budget
    - shipit_agent.costs.tracker
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shipit_agent.costs.budget import Budget, BudgetExceededError
from shipit_agent.costs.pricing import MODEL_ALIASES, MODEL_PRICING
from shipit_agent.costs.tracker import (
    CostRecord,
    CostTracker,
    _extract_model,
    _extract_usage,
)
from shipit_agent.hooks import AgentHooks
from shipit_agent.notifications.base import SEVERITY_ORDER, Notification
from shipit_agent.notifications.discord import DiscordNotifier
from shipit_agent.notifications.discord import _SEVERITY_COLOURS as DISCORD_COLOURS
from shipit_agent.notifications.manager import NotificationManager
from shipit_agent.notifications.slack import SlackNotifier
from shipit_agent.notifications.slack import _SEVERITY_COLOURS as SLACK_COLOURS
from shipit_agent.notifications.telegram import TelegramNotifier
from shipit_agent.notifications.templates import render_template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notification(**overrides) -> Notification:
    """Create a Notification with sensible defaults, allowing overrides."""
    defaults = dict(
        event="run_started",
        title="Test Title",
        message="Test message body",
        severity="info",
        metadata={"agent": "test-agent"},
        timestamp=datetime(2026, 1, 15, 12, 0, 0),
    )
    defaults.update(overrides)
    return Notification(**defaults)


def _mock_urlopen(status=200, body=b"ok"):
    """Return a MagicMock that behaves as a context-manager HTTP response."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.read.return_value = body
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class MockNotifier:
    """Async-compatible mock notifier for manager tests."""

    name = "mock"

    def __init__(self, success: bool = True) -> None:
        self._success = success
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return self._success

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
        return [await self.send(n) for n in notifications]


class FailingNotifier:
    """Mock notifier that always raises."""

    name = "failing"

    async def send(self, notification: Notification) -> bool:
        raise RuntimeError("boom")

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
        return [await self.send(n) for n in notifications]


# ===================================================================
# Notification (base)
# ===================================================================


class TestNotification:
    """Tests for shipit_agent.notifications.base.Notification."""

    def test_default_values(self) -> None:
        """severity defaults to 'info', metadata to {}, timestamp is set."""
        n = Notification(event="test", title="T", message="M")
        assert n.severity == "info"
        assert n.metadata == {}
        assert isinstance(n.timestamp, datetime)

    def test_custom_values(self) -> None:
        """All fields can be explicitly set."""
        ts = datetime(2026, 3, 1, 10, 30, 0)
        n = Notification(
            event="run_completed",
            title="Done",
            message="Finished",
            severity="warning",
            metadata={"key": "val"},
            timestamp=ts,
        )
        assert n.event == "run_completed"
        assert n.title == "Done"
        assert n.message == "Finished"
        assert n.severity == "warning"
        assert n.metadata == {"key": "val"}
        assert n.timestamp == ts

    def test_to_dict(self) -> None:
        """Serialisation includes all fields; timestamp as ISO string."""
        ts = datetime(2026, 6, 15, 8, 0, 0)
        n = Notification(
            event="cost_alert",
            title="Budget",
            message="Over budget",
            severity="critical",
            metadata={"cost": "5.00"},
            timestamp=ts,
        )
        d = n.to_dict()
        assert d["event"] == "cost_alert"
        assert d["title"] == "Budget"
        assert d["message"] == "Over budget"
        assert d["severity"] == "critical"
        assert d["metadata"] == {"cost": "5.00"}
        assert d["timestamp"] == "2026-06-15T08:00:00"


# ===================================================================
# SEVERITY_ORDER
# ===================================================================


class TestSeverityOrder:
    """Tests for severity level ordering."""

    def test_severity_ordering(self) -> None:
        """info < warning < error < critical."""
        assert SEVERITY_ORDER["info"] < SEVERITY_ORDER["warning"]
        assert SEVERITY_ORDER["warning"] < SEVERITY_ORDER["error"]
        assert SEVERITY_ORDER["error"] < SEVERITY_ORDER["critical"]

    def test_all_levels_present(self) -> None:
        """All four severity levels are defined."""
        assert set(SEVERITY_ORDER.keys()) == {"info", "warning", "error", "critical"}


# ===================================================================
# render_template
# ===================================================================


class TestRenderTemplate:
    """Tests for shipit_agent.notifications.templates.render_template."""

    def test_basic_render(self) -> None:
        """All variables provided are substituted."""
        result = render_template("{agent} started: {prompt}", agent="bot", prompt="hi")
        assert result == "bot started: hi"

    def test_missing_vars(self) -> None:
        """Unresolved placeholders stay as {var}."""
        result = render_template("{agent} started: {prompt}", agent="bot")
        assert result == "bot started: {prompt}"

    def test_empty_template(self) -> None:
        """Empty template returns empty string."""
        assert render_template("") == ""

    def test_no_vars_in_template(self) -> None:
        """Plain text without placeholders is returned unchanged."""
        assert render_template("hello world") == "hello world"


# ===================================================================
# SlackNotifier
# ===================================================================


class TestSlackNotifier:
    """Tests for shipit_agent.notifications.slack.SlackNotifier."""

    def setup_method(self) -> None:
        self.notifier = SlackNotifier(
            webhook_url="https://hooks.slack.com/test",
            channel="#general",
            username="TestBot",
        )
        self.notification = _make_notification()

    def test_build_blocks(self) -> None:
        """Verify header, section, fields, and context blocks."""
        blocks = self.notifier._build_blocks(self.notification)
        # Block types in order: header, section (message), section (fields), context
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["text"] == "Test Title"
        assert blocks[1]["type"] == "section"
        assert blocks[1]["text"]["text"] == "Test message body"
        # Metadata fields block
        assert blocks[2]["type"] == "section"
        assert "fields" in blocks[2]
        # Context block (last)
        assert blocks[-1]["type"] == "context"

    def test_build_payload_has_attachments(self) -> None:
        """Payload includes attachments with colour from severity."""
        payload = self.notifier._build_payload(self.notification)
        assert "attachments" in payload
        assert len(payload["attachments"]) == 1
        assert "color" in payload["attachments"][0]
        assert "blocks" in payload["attachments"][0]

    def test_severity_colors(self) -> None:
        """All four severity levels produce the expected hex colours."""
        assert SLACK_COLOURS["info"] == "#3498db"
        assert SLACK_COLOURS["warning"] == "#f1c40f"
        assert SLACK_COLOURS["error"] == "#e74c3c"
        assert SLACK_COLOURS["critical"] == "#992d22"

    def test_channel_override(self) -> None:
        """Channel field is included when set in the constructor."""
        payload = self.notifier._build_payload(self.notification)
        assert payload["channel"] == "#general"

        # Without channel
        notifier_no_channel = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        payload2 = notifier_no_channel._build_payload(self.notification)
        assert "channel" not in payload2

    def test_send_sync_success(self) -> None:
        """Mocked urllib returns 200 -> send_sync returns True."""
        mock_resp = _mock_urlopen(status=200)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.notifier.send_sync(self.notification)
        assert result is True

    def test_send_sync_failure(self) -> None:
        """urllib raises URLError -> send_sync returns False."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection error"),
        ):
            result = self.notifier.send_sync(self.notification)
        assert result is False


# ===================================================================
# DiscordNotifier
# ===================================================================


class TestDiscordNotifier:
    """Tests for shipit_agent.notifications.discord.DiscordNotifier."""

    def setup_method(self) -> None:
        self.notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            username="TestBot",
            avatar_url="https://example.com/avatar.png",
        )
        self.notification = _make_notification()

    def test_build_embed(self) -> None:
        """Verify title, description, color, fields, footer."""
        embed = self.notifier._build_embed(self.notification)
        assert embed["title"] == "Test Title"
        assert embed["description"] == "Test message body"
        assert "color" in embed
        assert "footer" in embed
        assert "fields" in embed  # metadata present
        assert embed["fields"][0]["name"] == "agent"

    def test_severity_colors(self) -> None:
        """All four severity levels produce correct decimal colours."""
        assert DISCORD_COLOURS["info"] == 0x3498DB
        assert DISCORD_COLOURS["warning"] == 0xF39C12
        assert DISCORD_COLOURS["error"] == 0xE74C3C
        assert DISCORD_COLOURS["critical"] == 0x992D22

    def test_avatar_url(self) -> None:
        """avatar_url is included in payload when set."""
        payload = self.notifier._build_payload(self.notification)
        assert payload["avatar_url"] == "https://example.com/avatar.png"

        # Without avatar_url
        notifier_no_avatar = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test"
        )
        payload2 = notifier_no_avatar._build_payload(self.notification)
        assert "avatar_url" not in payload2

    def test_send_sync_success(self) -> None:
        """Mocked urllib returns 204 -> send_sync returns True."""
        mock_resp = _mock_urlopen(status=204)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.notifier.send_sync(self.notification)
        assert result is True

    def test_send_sync_failure(self) -> None:
        """urllib raises URLError -> send_sync returns False."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection error"),
        ):
            result = self.notifier.send_sync(self.notification)
        assert result is False


# ===================================================================
# TelegramNotifier
# ===================================================================


class TestTelegramNotifier:
    """Tests for shipit_agent.notifications.telegram.TelegramNotifier."""

    def setup_method(self) -> None:
        self.notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        self.notification = _make_notification()

    def test_format_markdown(self) -> None:
        """Verify emoji, title, message, metadata, and footer in output."""
        text = self.notifier._format_markdown(self.notification)
        # Should contain the title (escaped)
        assert "Test Title" in text or "Test\\ Title" in text
        # Should contain the message
        assert "Test message body" in text or "Test\\ message\\ body" in text
        # Should contain metadata key
        assert "agent" in text
        # Should contain severity
        assert "info" in text

    def test_escape_special_chars(self) -> None:
        """Verify special MarkdownV2 characters are escaped."""
        text = TelegramNotifier._escape("_*[]()~`>#+\\-=|{}.!")
        # Every special char should be preceded by a backslash
        assert "\\_" in text
        assert "\\*" in text
        assert "\\[" in text
        assert "\\]" in text
        assert "\\(" in text
        assert "\\)" in text
        assert "\\~" in text
        assert "\\`" in text
        assert "\\>" in text
        assert "\\#" in text
        assert "\\+" in text
        assert "\\-" in text
        assert "\\=" in text
        assert "\\|" in text
        assert "\\{" in text
        assert "\\}" in text
        assert "\\." in text
        assert "\\!" in text

    def test_send_sync_success(self) -> None:
        """Mocked urllib with {"ok": true} -> send_sync returns True."""
        body = json.dumps({"ok": True}).encode("utf-8")
        mock_resp = _mock_urlopen(status=200, body=body)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.notifier.send_sync(self.notification)
        assert result is True

    def test_send_sync_failure(self) -> None:
        """urllib raises URLError -> send_sync returns False."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection error"),
        ):
            result = self.notifier.send_sync(self.notification)
        assert result is False


# ===================================================================
# NotificationManager
# ===================================================================


class TestNotificationManager:
    """Tests for shipit_agent.notifications.manager.NotificationManager."""

    def test_notify_dispatches_to_all(self) -> None:
        """Two mock notifiers both receive the notification."""
        n1 = MockNotifier()
        n2 = MockNotifier()
        manager = NotificationManager(notifiers=[n1, n2])
        notification = _make_notification()

        results = asyncio.run(manager.notify(notification))
        assert results == {"mock": True, "mock": True}
        assert len(n1.sent) == 1
        assert len(n2.sent) == 1

    def test_severity_filter(self) -> None:
        """min_severity='error' skips info and warning notifications."""
        n = MockNotifier()
        manager = NotificationManager(notifiers=[n], min_severity="error")

        info_note = _make_notification(severity="info")
        warn_note = _make_notification(severity="warning")
        error_note = _make_notification(severity="error")

        asyncio.run(manager.notify(info_note))
        asyncio.run(manager.notify(warn_note))
        asyncio.run(manager.notify(error_note))

        # Only the error notification should have been sent
        assert len(n.sent) == 1
        assert n.sent[0].severity == "error"

    def test_event_filter(self) -> None:
        """Only specified events are dispatched."""
        n = MockNotifier()
        manager = NotificationManager(
            notifiers=[n], events=["run_started"]
        )

        started = _make_notification(event="run_started")
        completed = _make_notification(event="run_completed")

        asyncio.run(manager.notify(started))
        asyncio.run(manager.notify(completed))

        assert len(n.sent) == 1
        assert n.sent[0].event == "run_started"

    def test_notify_catches_exceptions(self) -> None:
        """A notifier that raises does not crash the manager."""
        failing = FailingNotifier()
        ok = MockNotifier()
        manager = NotificationManager(notifiers=[failing, ok])
        notification = _make_notification()

        results = asyncio.run(manager.notify(notification))
        assert results["failing"] is False
        assert results["mock"] is True

    def test_notify_sync(self) -> None:
        """Synchronous wrapper dispatches correctly."""
        n = MockNotifier()
        manager = NotificationManager(notifiers=[n])
        notification = _make_notification()

        results = manager.notify_sync(notification)
        assert results["mock"] is True
        assert len(n.sent) == 1

    def test_as_hooks_returns_hooks(self) -> None:
        """as_hooks() returns an AgentHooks instance."""
        manager = NotificationManager(notifiers=[MockNotifier()])
        hooks = manager.as_hooks(agent_name="test-agent")
        assert isinstance(hooks, AgentHooks)

    def test_should_notify_respects_severity(self) -> None:
        """_should_notify filters by min_severity correctly."""
        manager = NotificationManager(notifiers=[], min_severity="warning")

        info = _make_notification(severity="info")
        warning = _make_notification(severity="warning")
        error = _make_notification(severity="error")
        critical = _make_notification(severity="critical")

        assert manager._should_notify(info) is False
        assert manager._should_notify(warning) is True
        assert manager._should_notify(error) is True
        assert manager._should_notify(critical) is True

    def test_should_notify_respects_events(self) -> None:
        """_should_notify filters by event names."""
        manager = NotificationManager(
            notifiers=[], events=["cost_alert", "tool_failed"]
        )

        assert manager._should_notify(_make_notification(event="cost_alert")) is True
        assert manager._should_notify(_make_notification(event="tool_failed")) is True
        assert manager._should_notify(_make_notification(event="run_started")) is False


# ===================================================================
# Budget
# ===================================================================


class TestBudget:
    """Tests for shipit_agent.costs.budget.Budget."""

    def test_should_warn_below_threshold(self) -> None:
        """Returns False when spent is below the warning threshold."""
        b = Budget(max_dollars=10.0, warn_at=0.80)
        assert b.should_warn(7.99) is False

    def test_should_warn_at_threshold(self) -> None:
        """Returns True at exactly 80% of budget."""
        b = Budget(max_dollars=10.0, warn_at=0.80)
        assert b.should_warn(8.00) is True

    def test_should_warn_above_threshold(self) -> None:
        """Returns True above the warning threshold."""
        b = Budget(max_dollars=10.0, warn_at=0.80)
        assert b.should_warn(9.50) is True

    def test_is_exceeded_below(self) -> None:
        """Returns False when spent is below the budget limit."""
        b = Budget(max_dollars=10.0)
        assert b.is_exceeded(9.99) is False

    def test_is_exceeded_at_limit(self) -> None:
        """Returns False at exactly the budget limit (not exceeded)."""
        b = Budget(max_dollars=10.0)
        assert b.is_exceeded(10.0) is False

    def test_is_exceeded_above(self) -> None:
        """Returns True when spent exceeds the budget limit."""
        b = Budget(max_dollars=10.0)
        assert b.is_exceeded(10.01) is True


# ===================================================================
# BudgetExceededError
# ===================================================================


class TestBudgetExceededError:
    """Tests for shipit_agent.costs.budget.BudgetExceededError."""

    def test_error_attributes(self) -> None:
        """spent, budget, model attributes are accessible."""
        err = BudgetExceededError(spent=5.5, budget=5.0, model="gpt-4o")
        assert err.spent == 5.5
        assert err.budget == 5.0
        assert err.model == "gpt-4o"

    def test_error_message(self) -> None:
        """Formatted string includes spent, budget, and model values."""
        err = BudgetExceededError(spent=5.5, budget=5.0, model="gpt-4o")
        msg = str(err)
        assert "5.5" in msg
        assert "5.0" in msg
        assert "gpt-4o" in msg


# ===================================================================
# CostRecord
# ===================================================================


class TestCostRecord:
    """Tests for shipit_agent.costs.tracker.CostRecord."""

    def test_to_dict(self) -> None:
        """All fields serialised; cost_usd rounded to 6 decimal places."""
        ts = datetime(2026, 4, 1, 12, 0, 0)
        rec = CostRecord(
            call_number=1,
            model="claude-sonnet-4",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_write_tokens=100,
            cost_usd=0.1234567890,
            timestamp=ts,
        )
        d = rec.to_dict()
        assert d["call_number"] == 1
        assert d["model"] == "claude-sonnet-4"
        assert d["input_tokens"] == 1000
        assert d["output_tokens"] == 500
        assert d["cache_read_tokens"] == 200
        assert d["cache_write_tokens"] == 100
        assert d["cost_usd"] == round(0.1234567890, 6)
        assert d["timestamp"] == "2026-04-01T12:00:00"


# ===================================================================
# CostTracker
# ===================================================================


class TestCostTracker:
    """Tests for shipit_agent.costs.tracker.CostTracker."""

    def test_initial_state(self) -> None:
        """New tracker has zero cost and no calls."""
        t = CostTracker()
        assert t.total_cost == 0.0
        assert t.total_tokens == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

    def test_record_call_claude_sonnet(self) -> None:
        """Claude Sonnet 4 pricing: 3.00/M input + 15.00/M output."""
        t = CostTracker()
        rec = t.record_call(
            model="claude-sonnet-4",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # 3.00 + 15.00 = 18.00
        assert rec.cost_usd == pytest.approx(18.0)
        assert t.total_cost == pytest.approx(18.0)

    def test_record_call_with_cache(self) -> None:
        """Cache read/write tokens use their own pricing rates."""
        t = CostTracker()
        rec = t.record_call(
            model="claude-sonnet-4",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            cache_write_tokens=1_000_000,
        )
        # cache_read: 0.30, cache_write: 3.75 -> total 4.05
        assert rec.cost_usd == pytest.approx(4.05)

    def test_record_call_unknown_model(self) -> None:
        """Unknown model returns $0.00 cost without crashing."""
        t = CostTracker()
        rec = t.record_call(
            model="unknown-model-xyz",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.cost_usd == 0.0
        assert t.total_cost == 0.0

    def test_calculate_cost_gpt4o(self) -> None:
        """GPT-4o pricing: 2.50/M input + 10.00/M output."""
        t = CostTracker()
        cost = t.calculate_cost(
            model="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == pytest.approx(12.5)

    def test_model_alias_resolution(self) -> None:
        """'opus' resolves to 'claude-opus-4'."""
        t = CostTracker()
        cost = t.calculate_cost(
            model="opus",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        # claude-opus-4 input price is 15.00 per million
        assert cost == pytest.approx(15.0)

    def test_total_tokens_accumulate(self) -> None:
        """Multiple calls aggregate token counts correctly."""
        t = CostTracker()
        t.record_call("claude-sonnet-4", input_tokens=100, output_tokens=50)
        t.record_call("claude-sonnet-4", input_tokens=200, output_tokens=75)
        tokens = t.total_tokens
        assert tokens["input_tokens"] == 300
        assert tokens["output_tokens"] == 125

    def test_breakdown_returns_records(self) -> None:
        """breakdown() returns a list of dicts with cost_usd."""
        t = CostTracker()
        t.record_call("claude-sonnet-4", input_tokens=100, output_tokens=50)
        t.record_call("gpt-4o", input_tokens=200, output_tokens=100)
        bd = t.breakdown()
        assert len(bd) == 2
        assert "cost_usd" in bd[0]
        assert "cost_usd" in bd[1]

    def test_summary_structure(self) -> None:
        """Summary has total_cost_usd, total_calls, total_tokens, calls."""
        t = CostTracker()
        t.record_call("claude-sonnet-4", input_tokens=100, output_tokens=50)
        s = t.summary()
        assert "total_cost_usd" in s
        assert "total_calls" in s
        assert "total_tokens" in s
        assert "calls" in s
        assert s["total_calls"] == 1

    def test_summary_with_budget(self) -> None:
        """Summary includes budget section with remaining and percent_used."""
        t = CostTracker(budget=Budget(max_dollars=10.0))
        t.record_call("claude-sonnet-4", input_tokens=100, output_tokens=50)
        s = t.summary()
        assert "budget" in s
        assert "remaining" in s["budget"]
        assert "percent_used" in s["budget"]
        assert s["budget"]["max_dollars"] == 10.0

    def test_add_model(self) -> None:
        """Custom model pricing is used after add_model()."""
        t = CostTracker()
        t.add_model("my-custom-model", {"input": 1.0, "output": 2.0})
        cost = t.calculate_cost("my-custom-model", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(3.0)

    def test_reset_clears_everything(self) -> None:
        """total_cost=0, calls empty after reset."""
        t = CostTracker()
        t.record_call("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        assert t.total_cost > 0
        t.reset()
        assert t.total_cost == 0.0
        assert t.breakdown() == []

    def test_budget_enforcement(self) -> None:
        """BudgetExceededError raised when budget is exceeded."""
        t = CostTracker(budget=Budget(max_dollars=0.001))
        with pytest.raises(BudgetExceededError) as exc_info:
            t.record_call("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)
        assert exc_info.value.spent > 0.001

    def test_budget_warning_emitted_once(self) -> None:
        """Warning callback is called exactly once when threshold is crossed."""
        alerts: list[tuple[float, float]] = []

        def on_alert(spent: float, budget: float) -> None:
            alerts.append((spent, budget))

        # Budget of $100, warn at 80% ($80).  Each call costs ~18.00.
        t = CostTracker(
            budget=Budget(max_dollars=100.0, warn_at=0.80),
            on_cost_alert=on_alert,
        )
        # 5 calls x ~$18 = ~$90 -> should trigger warning once
        for _ in range(5):
            t.record_call("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)

        assert len(alerts) == 1

    def test_budget_warning_not_emitted_below(self) -> None:
        """No warning callback below the threshold."""
        alerts: list[tuple[float, float]] = []

        def on_alert(spent: float, budget: float) -> None:
            alerts.append((spent, budget))

        t = CostTracker(
            budget=Budget(max_dollars=1000.0, warn_at=0.80),
            on_cost_alert=on_alert,
        )
        # One call costs ~$18, well below $800 threshold
        t.record_call("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)
        assert len(alerts) == 0

    def test_as_hooks_returns_hooks(self) -> None:
        """as_hooks() returns an AgentHooks instance."""
        t = CostTracker()
        hooks = t.as_hooks(model_name="claude-sonnet-4")
        assert isinstance(hooks, AgentHooks)

    def test_no_budget_no_error(self) -> None:
        """No budget set -> no error regardless of spend."""
        t = CostTracker()
        # Record many expensive calls — should not raise
        for _ in range(10):
            t.record_call("claude-opus-4", input_tokens=1_000_000, output_tokens=1_000_000)
        assert t.total_cost > 0


# ===================================================================
# _extract_usage / _extract_model helpers
# ===================================================================


class TestExtractUsage:
    """Tests for shipit_agent.costs.tracker._extract_usage."""

    def test_extract_from_dict(self) -> None:
        """response.usage as a plain dict is returned directly."""
        response = SimpleNamespace(usage={"input_tokens": 100, "output_tokens": 50})
        result = _extract_usage(response)
        assert result == {"input_tokens": 100, "output_tokens": 50}

    def test_extract_from_anthropic_object(self) -> None:
        """response.usage with input_tokens attribute (Anthropic SDK style)."""
        usage = SimpleNamespace(input_tokens=200, output_tokens=100)
        response = SimpleNamespace(usage=usage)
        result = _extract_usage(response)
        assert result is not None
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 100

    def test_extract_from_openai_object(self) -> None:
        """response.usage with prompt_tokens attribute (OpenAI SDK style)."""
        usage = SimpleNamespace(prompt_tokens=300, completion_tokens=150)
        response = SimpleNamespace(usage=usage)
        result = _extract_usage(response)
        assert result is not None
        assert result["prompt_tokens"] == 300
        assert result["completion_tokens"] == 150

    def test_extract_from_metadata(self) -> None:
        """response.metadata['usage'] dict is extracted."""
        response = SimpleNamespace(
            metadata={"usage": {"input_tokens": 400, "output_tokens": 200}}
        )
        result = _extract_usage(response)
        assert result == {"input_tokens": 400, "output_tokens": 200}

    def test_extract_returns_none(self) -> None:
        """No usage info found -> returns None."""
        response = SimpleNamespace()
        assert _extract_usage(response) is None


class TestExtractModel:
    """Tests for shipit_agent.costs.tracker._extract_model."""

    def test_extract_from_response_model(self) -> None:
        """response.model attribute is returned."""
        response = SimpleNamespace(model="claude-sonnet-4")
        assert _extract_model(response) == "claude-sonnet-4"

    def test_extract_from_metadata(self) -> None:
        """response.metadata['model'] is returned."""
        response = SimpleNamespace(metadata={"model": "gpt-4o"})
        assert _extract_model(response) == "gpt-4o"

    def test_extract_returns_none(self) -> None:
        """No model info found -> returns None."""
        response = SimpleNamespace()
        assert _extract_model(response) is None


# ===================================================================
# MODEL_PRICING / MODEL_ALIASES
# ===================================================================


class TestModelPricing:
    """Tests for shipit_agent.costs.pricing tables."""

    def test_claude_models_present(self) -> None:
        """All 6 Claude models are in the pricing table."""
        claude_models = [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
            "claude-opus-4",
            "claude-sonnet-4",
            "claude-haiku-4",
        ]
        for model in claude_models:
            assert model in MODEL_PRICING, f"{model} missing from MODEL_PRICING"

    def test_openai_models_present(self) -> None:
        """gpt-4o and gpt-4o-mini are in the pricing table."""
        assert "gpt-4o" in MODEL_PRICING
        assert "gpt-4o-mini" in MODEL_PRICING

    def test_google_models_present(self) -> None:
        """Gemini models are in the pricing table."""
        assert "gemini-2.5-pro" in MODEL_PRICING
        assert "gemini-2.5-flash" in MODEL_PRICING
        assert "gemini-2.0-flash" in MODEL_PRICING

    def test_bedrock_models_present(self) -> None:
        """Bedrock model IDs are in the pricing table."""
        assert "anthropic.claude-sonnet-4-20250514-v1:0" in MODEL_PRICING
        assert "anthropic.claude-haiku-4-20250514-v1:0" in MODEL_PRICING

    def test_aliases_resolve(self) -> None:
        """All aliases map to valid pricing keys."""
        for alias, canonical in MODEL_ALIASES.items():
            assert canonical in MODEL_PRICING, (
                f"Alias '{alias}' -> '{canonical}' not found in MODEL_PRICING"
            )
