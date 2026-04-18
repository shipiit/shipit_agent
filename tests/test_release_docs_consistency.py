"""Release-note, docs, and notebook consistency checks for the v1.0.5 refresh."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_root_changelog_includes_v1_0_5_entry() -> None:
    """The repository changelog should advertise the current package version."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.0.5] — 2026-04-18" in changelog
    assert (
        "Prebuilt agents, multi-agent crews, notifications, and cost tracking"
        in changelog
    )


def test_docs_homepage_tip_is_updated_to_v1_0_5() -> None:
    """The docs landing page should not still headline the older v1.0.3 release."""
    index_doc = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    assert (
        '!!! tip "v1.0.5 — Prebuilt Agents, ShipCrew, Notifications, Cost Tracking"'
        in index_doc
    )
    assert '!!! tip "v1.0.3 — Super RAG, DeepAgent, live chat REPL"' not in index_doc


def test_docs_changelog_does_not_reference_missing_v1_0_5_guides() -> None:
    """Release notes should not point at docs files that do not exist in the repo."""
    docs_changelog = (ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")

    missing_paths = [
        "guides/prebuilt-agents.md",
        "deep-agents/ship-crew.md",
        "guides/notifications.md",
        "guides/cost-tracking.md",
    ]
    for rel_path in missing_paths:
        assert not (ROOT / "docs" / rel_path).exists()
        assert rel_path not in docs_changelog


def test_docs_changelog_notebook_summary_matches_checked_in_notebooks() -> None:
    """The notebook summary should use the current checked-in notebook counts."""
    docs_changelog = (ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")
    assert "## v1.0.5 — 2026-04-18" in docs_changelog
    assert "Notebook 32" in docs_changelog and "(27 cells)" in docs_changelog
    assert "Notebook 33" in docs_changelog and "(28 cells)" in docs_changelog
    assert "Notebook 34" in docs_changelog and "(27 cells)" in docs_changelog
    assert "Notebook 35" in docs_changelog and "(31 cells)" in docs_changelog


def test_v1_0_5_notebooks_cover_documented_topics() -> None:
    """The four v1.0.5 notebooks should contain their key documented examples."""
    expected_markers = {
        "32_prebuilt_agents.ipynb": [
            "AgentRegistry.default()",
            "registry.search(",
            "AgentDefinition.from_dict(",
            "AgentRegistry([custom_agent])",
            "ShipCrew",
            "mini_crew = ShipCrew(",
            "reviewer_sa = ShipAgent(",
        ],
        "33_ship_crew_orchestration.ipynb": [
            "ShipCrew(",
            "## 3. Parallel Execution Mode",
            "## 4. Hierarchical (LLM-Driven) Mode",
            "crew.stream(",
            "event_types = [event.type for event in crew_stream.stream()]",
            "ShipAgent.from_registry(",
            "create_ship_crew(",
            "CostTracker",
            "output_schema={",
        ],
        "34_notifications.ipynb": [
            "Notification(",
            "SlackNotifier(",
            "DiscordNotifier(",
            "TelegramNotifier(",
            "NotificationManager(",
            "manager.as_hooks(",
            "render_template(",
            'notify_hooks = manager.as_hooks(agent_name=\\"demo-agent\\")',
            "cost_hooks = tracker.as_hooks()",
            "run_completed (final LLM response only)",
            "Budget alerts",
        ],
        "35_cost_tracking_and_budgets.ipynb": [
            "MODEL_PRICING",
            "calculate_cost(",
            "record_call(",
            "BudgetExceededError",
            "add_model(",
            "tracker.as_hooks(",
            "tracker.summary(",
        ],
    }

    notebook_dir = ROOT / "notebooks"
    for name, markers in expected_markers.items():
        text = (notebook_dir / name).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text
