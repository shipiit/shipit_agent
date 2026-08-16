"""Agent rules — scope resolution, precedence, rendering, tool-level rules, and
file discovery (AGENTS.md + .shipit/rules/ with frontmatter)."""

from __future__ import annotations

import pytest

from shipit_agent.rules import (
    Rule,
    RuleSet,
    coerce_rule,
    collect_tool_rules,
    load_project_rules,
)


# ── Rule.applies (scope) ──────────────────────────────────────────────────────


def test_unscoped_rule_applies_everywhere():
    assert Rule(text="x").applies()
    assert Rule(text="x").applies(tools=frozenset({"bash"}), paths=("a.py",))


def test_tool_scoped_rule_hidden_without_the_tool():
    rule = Rule(text="no rm -rf", tools=("bash",))
    assert not rule.applies(tools=frozenset({"read_file"}))
    assert rule.applies(tools=frozenset({"bash", "read_file"}))


def test_path_scoped_rule_matches_by_glob():
    rule = Rule(text="pytest only", paths=("tests/**",))
    assert rule.applies(paths=("tests/test_x.py",))
    assert not rule.applies(paths=("src/main.py",))


def test_path_scoped_rule_shows_when_paths_unknown():
    # No paths in context → don't suppress a path rule (show-if-unsure).
    assert Rule(text="pytest only", paths=("tests/**",)).applies()


# ── coercion ──────────────────────────────────────────────────────────────────


def test_coerce_from_string_and_dict():
    assert coerce_rule("be nice").text == "be nice"
    r = coerce_rule({"text": "x", "paths": ["a/**"], "tools": ["bash"], "priority": 3})
    assert r.paths == ("a/**",) and r.tools == ("bash",) and r.priority == 3


def test_coerce_rejects_garbage():
    with pytest.raises(TypeError):
        coerce_rule(42)


# ── RuleSet: precedence + rendering ───────────────────────────────────────────


def test_priority_orders_highest_first_stable_within_tier():
    rs = RuleSet()
    rs.add({"text": "low", "priority": 1})
    rs.add({"text": "high-a", "priority": 10})
    rs.add({"text": "high-b", "priority": 10})
    ordered = [r.text for r in rs.for_context()]
    assert ordered == ["high-a", "high-b", "low"]   # stable within equal priority


def test_blank_rules_are_dropped():
    rs = RuleSet().add("   ").add("real")
    assert len(rs) == 1 and rs.rules[0].text == "real"


def test_render_empty_is_empty_string():
    assert RuleSet().render() == ""
    # a set whose only rule is filtered out also renders empty
    rs = RuleSet().add({"text": "bash only", "tools": ["bash"]})
    assert rs.render(tools=frozenset({"read_file"})) == ""


def test_render_produces_numbered_block():
    rs = RuleSet().add("first").add("second")
    out = rs.render()
    assert out.startswith("# Rules")
    assert "1. first" in out and "2. second" in out


def test_render_filters_by_context():
    rs = RuleSet()
    rs.add("global")
    rs.add({"text": "bash rule", "tools": ["bash"]})
    rs.add({"text": "test rule", "paths": ["tests/**"]})
    out = rs.render(tools=frozenset({"bash"}), paths=("src/app.py",))
    assert "global" in out and "bash rule" in out
    assert "test rule" not in out           # path didn't match


# ── tool-level rules ──────────────────────────────────────────────────────────


class _Tool:
    def __init__(self, name, rules=None):
        self.name = name
        if rules is not None:
            self.rules = rules


def test_collect_tool_rules_scopes_to_the_tool():
    tools = [_Tool("bash", rules=["never run rm -rf /"]), _Tool("read_file")]
    collected = collect_tool_rules(tools)
    assert len(collected) == 1
    rule = collected[0]
    assert rule.tools == ("bash",) and rule.source == "tool:bash"
    # And it only surfaces when bash is active.
    assert rule.applies(tools=frozenset({"bash"}))
    assert not rule.applies(tools=frozenset({"read_file"}))


def test_tool_rule_end_to_end_in_a_ruleset():
    tools = [_Tool("bash", rules=[{"text": "quote your paths", "priority": 2}])]
    rs = RuleSet().extend(collect_tool_rules(tools))
    assert "quote your paths" in rs.render(tools=frozenset({"bash"}))
    assert rs.render(tools=frozenset({"read_file"})) == ""   # hidden without bash


# ── file discovery ────────────────────────────────────────────────────────────


def test_load_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# House rules\nUse tabs, not spaces.", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert len(rules) == 1
    assert "Use tabs" in rules[0].text and rules[0].id == "agents-md"


def test_load_rules_dir_with_frontmatter(tmp_path):
    pytest.importorskip("yaml")
    d = tmp_path / ".shipit" / "rules"
    d.mkdir(parents=True)
    (d / "tests.md").write_text(
        '---\npaths: ["tests/**"]\npriority: 10\n---\nUse pytest, never unittest.',
        encoding="utf-8",
    )
    rules = load_project_rules(tmp_path)
    rule = next(r for r in rules if r.id == "tests")
    assert rule.paths == ("tests/**",) and rule.priority == 10
    assert "Use pytest" in rule.text


def test_load_rules_dir_body_only_without_frontmatter(tmp_path):
    d = tmp_path / ".shipit" / "rules"
    d.mkdir(parents=True)
    (d / "plain.md").write_text("Just a plain rule.", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert any(r.text == "Just a plain rule." for r in rules)


def test_missing_sources_are_not_an_error(tmp_path):
    assert load_project_rules(tmp_path) == []       # empty project, no crash


def test_include_agents_md_toggle(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Global house rule.", encoding="utf-8")
    assert load_project_rules(tmp_path, include_agents_md=False) == []
    assert len(load_project_rules(tmp_path, include_agents_md=True)) == 1


# ── Agent integration ─────────────────────────────────────────────────────────


class _LLM:
    def complete(self, *a, **k):  # never called in these tests
        raise AssertionError("LLM should not run")


def test_agent_injects_rules_priority_ordered():
    from shipit_agent.agent import Agent

    agent = Agent(
        llm=_LLM(), project_root="/tmp", prompt="BASE",
        rules=["write a test first", {"text": "never touch prod", "priority": 10}],
    )
    effective = agent._effective_prompt("do a thing")
    assert "# Rules" in effective
    assert effective.index("never touch prod") < effective.index("write a test first")


def test_agent_tool_rules_surface_only_with_the_tool():
    from shipit_agent.agent import Agent

    class _BashTool:
        name = "bash"
        rules = ["never run rm -rf /"]
        def schema(self):
            return {"type": "function", "function": {"name": "bash", "parameters": {}}}
        def run(self, *a, **k):
            ...

    with_bash = Agent(llm=_LLM(), project_root="/tmp", prompt="BASE", tools=[_BashTool()])
    assert "never run rm -rf /" in with_bash._effective_prompt("x")

    without = Agent(llm=_LLM(), project_root="/tmp", prompt="BASE")
    assert "never run rm -rf /" not in without._effective_prompt("x")


def test_agent_with_no_rules_leaves_prompt_clean():
    from shipit_agent.agent import Agent

    agent = Agent(llm=_LLM(), project_root="/tmp", prompt="BASE")
    assert "# Rules" not in agent._effective_prompt("x")


def test_rules_appended_after_construction_take_effect():
    from shipit_agent.agent import Agent

    agent = Agent(llm=_LLM(), project_root="/tmp", prompt="BASE")
    agent.rules.append("never force-push")            # live mutation
    assert "never force-push" in agent._effective_prompt("x")


def test_with_builtins_carries_rules():
    from shipit_agent.agent import Agent

    agent = Agent.with_builtins(llm=_LLM(), project_root="/tmp", rules=["no secrets in logs"])
    assert "no secrets in logs" in agent._effective_prompt("x")


def test_clone_keeps_independent_rules():
    from shipit_agent.agent import Agent

    a = Agent(llm=_LLM(), project_root="/tmp", prompt="BASE", rules=["shared"])
    b = a.clone()
    b.rules.append("only-b")
    assert "only-b" in b._effective_prompt("x")
    assert "only-b" not in a._effective_prompt("x")   # lists are independent
