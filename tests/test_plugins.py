"""The plugin system: manifest-per-directory discovery from three sources
(bundled, user dir, entry points), activation into tools + hooks, and the
Agent(plugins=...) integration.

Like the connector and provider catalogs, a plugin is a directory with a
declarative manifest; these tests double as a schema guard and prove the
override precedence and skip-invalid-with-diagnostic contract.
"""

from __future__ import annotations

import pytest

from shipit_agent.hooks import AgentHooks
from shipit_agent.plugins import (
    HOOK_POINTS,
    Plugin,
    PluginManifestError,
    PluginRegistrar,
    activate,
    apply_to_hooks,
    get_plugin,
    list_plugins,
    merge_plugins,
    parse_manifest,
    plugin_names,
)
from shipit_agent.plugins import registry as reg


# ── catalog loads cleanly ────────────────────────────────────────────────


def test_bundled_plugins_load():
    names = set(plugin_names())
    assert {"audit-log", "word-count"} <= names
    assert reg.PLUGIN_DIAGNOSTICS == []


def test_word_count_is_a_tool_pack():
    reg_ = activate(["word-count"])
    assert [t.name for t in reg_.tools] == ["word_count"]
    out = reg_.tools[0].run(text="one two three")
    assert out.metadata["words"] == 3


def test_audit_log_is_a_hook_pack():
    reg_ = activate(["audit-log"])
    assert not reg_.tools
    assert "after_tool" in reg_.hook_callbacks


def test_activate_merges_multiple():
    reg_ = activate(["word-count", "audit-log"])
    assert [t.name for t in reg_.tools] == ["word_count"]
    assert "after_tool" in reg_.hook_callbacks


def test_activate_unknown_name_raises():
    with pytest.raises(KeyError, match="unknown plugin"):
        activate(["does-not-exist"])


def test_audit_log_hook_writes_a_line(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("SHIPIT_AUDIT_LOG", str(log))
    reg_ = activate(["audit-log"])
    hook = reg_.hook_callbacks["after_tool"][0]
    assert hook("bash", "output") is None  # observe-only, never mutates
    assert "bash" in log.read_text()


def test_word_count_tool_schema():
    tool = activate(["word-count"]).tools[0]
    schema = tool.schema()
    assert schema["function"]["name"] == "word_count"
    assert "text" in schema["function"]["parameters"]["properties"]


# ── manifest parsing / validation ────────────────────────────────────────


def test_parse_minimal():
    p = parse_manifest({"name": "x"})
    assert p.name == "x" and p.kind == "standalone"


def test_parse_rejects_non_mapping():
    with pytest.raises(PluginManifestError, match="must be a mapping"):
        parse_manifest(["nope"])  # type: ignore[arg-type]


def test_parse_rejects_bad_version():
    with pytest.raises(PluginManifestError, match="plugin_version"):
        parse_manifest({"plugin_version": 2, "name": "x"})


def test_parse_requires_name():
    with pytest.raises(PluginManifestError, match="missing required field 'name'"):
        parse_manifest({"description": "y"})


def test_parse_rejects_invalid_name():
    with pytest.raises(PluginManifestError, match="invalid name"):
        parse_manifest({"name": "bad name!"})


def test_parse_rejects_unknown_kind():
    with pytest.raises(PluginManifestError, match="unsupported kind"):
        parse_manifest({"name": "x", "kind": "wizardry"})


def test_parse_rejects_unknown_hook_point():
    with pytest.raises(PluginManifestError, match="unknown hook point"):
        parse_manifest({"name": "x", "hooks": ["on_full_moon"]})


def test_parse_accepts_string_fields_as_single_item_lists():
    p = parse_manifest({"name": "x", "provides_tools": "solo", "hooks": "after_tool"})
    assert p.provides_tools == ["solo"] and p.hooks == ["after_tool"]


def test_user_dirs_include_shipit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIPIT_HOME", str(tmp_path))
    monkeypatch.delenv("SHIPIT_PLUGINS_DIR", raising=False)
    assert (tmp_path / "plugins") in reg._user_dirs()


# ── registrar ─────────────────────────────────────────────────────────────


def test_registrar_add_hook_rejects_bad_point():
    r = PluginRegistrar()
    with pytest.raises(ValueError, match="unknown hook point"):
        r.add_hook("nope", lambda: None)


def test_registrar_collects_tools_and_hooks():
    r = PluginRegistrar()
    r.add_tool(object())
    for point in HOOK_POINTS:
        r.add_hook(point, lambda *a, **k: None)
    assert len(r.tools) == 1
    assert set(r.hook_callbacks) == set(HOOK_POINTS)


# ── folding into AgentHooks ───────────────────────────────────────────────


def test_apply_to_hooks_extends_agenthooks():
    r = PluginRegistrar()
    called = []
    r.add_hook("after_tool", lambda name, result: called.append(name))
    hooks = apply_to_hooks(r)
    assert len(hooks.after_tool) == 1
    hooks.after_tool[0]("bash", "ok")
    assert called == ["bash"]


def test_apply_to_hooks_preserves_existing():
    existing = AgentHooks()
    existing.after_tool.append(lambda n, r: None)
    r = PluginRegistrar()
    r.add_hook("after_tool", lambda n, res: None)
    hooks = apply_to_hooks(r, existing)
    assert hooks is existing and len(hooks.after_tool) == 2


def test_merge_plugins_empty_is_noop():
    tools, hooks = merge_plugins([], tools=[1, 2])
    assert tools == [1, 2] and hooks is None


def test_merge_plugins_by_name_and_object():
    tools, hooks = merge_plugins(["word-count", get_plugin("audit-log")], tools=["seed"])
    names = [getattr(t, "name", t) for t in tools]
    assert "seed" in names and "word_count" in names
    assert isinstance(hooks, AgentHooks) and len(hooks.after_tool) == 1


# ── discovery: user dir override + skip-invalid ───────────────────────────


def _fresh_scan(tmp_path, monkeypatch, *, source="user"):
    """Reset the registry and scan a temp plugin root; restore after."""
    saved_reg = dict(reg._REGISTRY)
    saved_diag = list(reg.PLUGIN_DIAGNOSTICS)
    saved_loaded = reg._loaded
    monkeypatch.setattr(reg, "_loaded", False)
    reg._REGISTRY.clear()
    reg.PLUGIN_DIAGNOSTICS.clear()
    return saved_reg, saved_diag, saved_loaded


def test_user_dir_overrides_bundled(tmp_path, monkeypatch):
    # A user plugin named like a bundled one wins (last-writer / user beats bundled).
    (tmp_path / "word-count").mkdir()
    (tmp_path / "word-count" / "plugin.yaml").write_text(
        "plugin_version: 1\nname: word-count\ndescription: MY override\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SHIPIT_PLUGINS_DIR", str(tmp_path))
    saved = _fresh_scan(tmp_path, monkeypatch)
    try:
        reg.load_catalog()
        assert get_plugin("word-count").description == "MY override"
        assert reg.PLUGIN_DIAGNOSTICS == []
    finally:
        reg._REGISTRY.clear(); reg._REGISTRY.update(saved[0])
        reg.PLUGIN_DIAGNOSTICS[:] = saved[1]
        monkeypatch.setattr(reg, "_loaded", saved[2])


def test_entry_point_plugins_are_discovered_when_opted_in(monkeypatch):
    import importlib.metadata as md

    class FakeEP:
        name = "third-party-pack"

        def load(self):
            return lambda: Plugin(name="third-party-pack", description="from a pip package")

    class BadEP:
        name = "broken-ep"

        def load(self):
            return lambda: "not a plugin"

    monkeypatch.setattr(md, "entry_points", lambda group=None: [FakeEP(), BadEP()])
    monkeypatch.setenv("SHIPIT_PLUGIN_ENTRY_POINTS", "1")  # opt in
    saved = _fresh_scan(None, monkeypatch)
    try:
        reg.load_catalog()
        assert get_plugin("third-party-pack").description == "from a pip package"
        assert any("broken-ep" in src for src, _e in reg.PLUGIN_DIAGNOSTICS)
    finally:
        reg._REGISTRY.clear(); reg._REGISTRY.update(saved[0])
        reg.PLUGIN_DIAGNOSTICS[:] = saved[1]
        monkeypatch.setattr(reg, "_loaded", saved[2])


def test_entry_point_plugins_are_off_by_default(monkeypatch):
    # Security: a pip-installed package's entry point must NOT auto-load —
    # loading it executes that package's code. Off unless explicitly enabled.
    import importlib.metadata as md

    loaded = []

    class SneakyEP:
        name = "sneaky"

        def load(self):
            loaded.append(True)
            return lambda: Plugin(name="sneaky")

    monkeypatch.setattr(md, "entry_points", lambda group=None: [SneakyEP()])
    monkeypatch.delenv("SHIPIT_PLUGIN_ENTRY_POINTS", raising=False)
    saved = _fresh_scan(None, monkeypatch)
    try:
        reg.load_catalog()
        assert get_plugin("sneaky") is None
        assert loaded == []  # the entry point was never even loaded
    finally:
        reg._REGISTRY.clear(); reg._REGISTRY.update(saved[0])
        reg.PLUGIN_DIAGNOSTICS[:] = saved[1]
        monkeypatch.setattr(reg, "_loaded", saved[2])


def test_invalid_plugin_is_skipped_with_diagnostic(tmp_path, monkeypatch):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "plugin.yaml").write_text(
        "plugin_version: 1\nname: broken\nhooks: [not_a_real_hook]\n", encoding="utf-8"
    )
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "plugin.yaml").write_text(
        "plugin_version: 1\nname: good\n", encoding="utf-8"
    )
    monkeypatch.setenv("SHIPIT_PLUGINS_DIR", str(tmp_path))
    saved = _fresh_scan(tmp_path, monkeypatch)
    try:
        reg.load_catalog()
        names = set(plugin_names())
        assert "good" in names and "broken" not in names
        assert any("broken" in src for src, _err in reg.PLUGIN_DIAGNOSTICS)
    finally:
        reg._REGISTRY.clear(); reg._REGISTRY.update(saved[0])
        reg.PLUGIN_DIAGNOSTICS[:] = saved[1]
        monkeypatch.setattr(reg, "_loaded", saved[2])


# ── Agent integration ─────────────────────────────────────────────────────


def test_agent_plugins_add_tools_and_hooks():
    from shipit_agent import Agent
    from shipit_agent.llms.simple import ShipitLLM

    agent = Agent(
        llm=ShipitLLM(), plugins=["word-count", "audit-log"],
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
    )
    assert any(getattr(t, "name", "") == "word_count" for t in agent.tools)
    assert len(agent.hooks.after_tool) == 1


def test_agent_without_plugins_is_unaffected():
    from shipit_agent import Agent
    from shipit_agent.llms.simple import ShipitLLM

    agent = Agent(
        llm=ShipitLLM(), auto_use_skills=False,
        auto_project_memory=False, skill_source=None,
    )
    assert agent.hooks is None  # untouched when no plugins
