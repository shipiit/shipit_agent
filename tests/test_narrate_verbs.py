"""The verb registry — every tool call must become a readable sentence."""

from __future__ import annotations

import pytest

from shipit_agent.builtins import get_builtin_tools
from shipit_agent.narrate.verbs import (
    VERBS,
    describe_count,
    describe_count_present,
    icon_for,
    is_read_only,
    pluralize,
    summarize,
)


class TestSummarize:
    @pytest.mark.parametrize(
        "name,args,expected",
        [
            ("read_file", {"path": "app.py"}, "Read app.py"),
            ("write_file", {"path": "out.txt"}, "Wrote out.txt"),
            ("edit_file", {"path": "app.py"}, "Edited app.py"),
            ("bash", {"command": "pytest -q"}, "Ran pytest -q"),
            ("web_search", {"query": "oklch"}, "Searched the web for oklch"),
            ("todo", {}, "Updated the todo list"),
        ],
    )
    def test_past_labels(self, name, args, expected) -> None:
        assert summarize(name, args).past_label() == expected

    def test_present_tense_mirrors_past(self) -> None:
        summary = summarize("read_file", {"path": "app.py"})
        assert summary.past_label() == "Read app.py"
        assert summary.present_label() == "Reading app.py"

    def test_url_target_is_the_host_not_the_url(self) -> None:
        summary = summarize("open_url", {"url": "https://github.com/a/b?c=1#d"})
        assert summary.past_label() == "Fetched github.com"

    def test_malformed_url_falls_back_to_the_raw_value(self) -> None:
        assert summarize("open_url", {"url": "not a url"}).target == "not a url"

    def test_code_target_is_the_first_non_blank_line(self) -> None:
        code = "\n\n  const risk = scoreAccounts(usage)\nmore()\n"
        assert summarize("run_code", {"code": code}).target == (
            "const risk = scoreAccounts(usage)"
        )

    def test_long_code_target_is_elided(self) -> None:
        target = summarize("run_code", {"code": "x = " + "y" * 200}).target
        assert len(target) == 60
        assert target.endswith("…")

    def test_multiline_command_collapses_to_one_line(self) -> None:
        assert "\n" not in summarize("bash", {"command": "a\nb\nc"}).past_label()

    def test_no_arguments_still_yields_a_label(self) -> None:
        assert summarize("read_file", {}).past_label() == "Read"

    def test_none_arguments_are_tolerated(self) -> None:
        assert summarize("bash").past_label() == "Ran"


class TestUnknownTools:
    """MCP servers and custom tools have unbounded names — never crash."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("search_issues", "Searched issues"),
            ("create_ticket", "Created ticket"),
            ("linear__create_issue", "Created issue"),
            ("server.do_thing", "Did thing"),
            ("deploy", "Deployed"),
            ("copy_files", "Copied files"),
        ],
    )
    def test_humanized_fallback(self, name, expected) -> None:
        assert summarize(name, {}).past_label() == expected

    def test_first_scalar_argument_becomes_the_target(self) -> None:
        summary = summarize("search_issues", {"query": "login bug", "limit": 10})
        assert summary.past_label() == "Searched issues login bug"

    def test_non_scalar_arguments_are_skipped(self) -> None:
        summary = summarize("do_thing", {"payload": {"a": 1}, "name": "widget"})
        assert summary.target == "widget"

    def test_empty_name_does_not_raise(self) -> None:
        assert summarize("", {}).past_label()

    def test_bizarre_names_do_not_raise(self) -> None:
        for name in ("___", "123", "a" * 300, "тест"):
            assert summarize(name, {}).past_label()


class TestCountLabels:
    @pytest.mark.parametrize(
        "name,count,expected",
        [
            ("read_file", 3, "Read 3 files"),
            ("write_file", 5, "Wrote 5 files"),
            ("edit_file", 3, "Made 3 edits"),
            ("run_code", 4, "Ran code 4 times"),
            ("sql", 3, "Ran 3 queries"),
            ("bash", 2, "Ran 2 commands"),
            ("github", 2, "Used GitHub 2 times"),
        ],
    )
    def test_past(self, name, count, expected) -> None:
        assert describe_count(name, count) == expected

    def test_present_mirrors_past(self) -> None:
        assert describe_count_present("write_file", 5) == "Writing 5 files"
        assert describe_count_present("edit_file", 3) == "Making 3 edits"

    def test_single_call_uses_the_bare_verb(self) -> None:
        # "Made 1 edit" never appears — the group label supplies the target.
        assert describe_count("edit_file", 1) == "Edited"
        assert describe_count("read_file", 1) == "Read"

    def test_no_label_repeats_a_word(self) -> None:
        """Guards the collision class: "Edited 3 edits", "Queried 3 queries"."""
        for name in VERBS:
            for label in (describe_count(name, 3), describe_count_present(name, 3)):
                stems = [word.lower().rstrip("s") for word in label.split()]
                assert len(stems) == len(set(stems)), f"{name}: {label!r}"


class TestReadOnly:
    def test_known_read_only_tools(self) -> None:
        assert is_read_only("read_file")
        assert is_read_only("web_search")
        assert is_read_only("grep_files")

    def test_known_mutating_tools(self) -> None:
        assert not is_read_only("write_file")
        assert not is_read_only("bash")
        assert not is_read_only("sql")

    def test_a_tools_own_declaration_wins(self) -> None:
        class Declared:
            read_only = True

        # bash is mutating by every heuristic; the attribute still wins.
        assert is_read_only("bash", Declared())

    def test_unknown_tool_falls_back_to_permission_heuristics(self) -> None:
        assert is_read_only("list_widgets")
        assert not is_read_only("widget_delete")


class TestCoverage:
    def test_every_builtin_has_a_hand_written_spec(self) -> None:
        names = {
            getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")
        }
        assert not names - set(VERBS), "builtins missing a VerbSpec"

    def test_every_spec_has_an_icon(self) -> None:
        for name in VERBS:
            assert icon_for(name)


class TestPluralize:
    @pytest.mark.parametrize(
        "count,singular,plural,expected",
        [
            (1, "file", None, "1 file"),
            (2, "file", None, "2 files"),
            (0, "file", None, "0 files"),
            (2, "query", "queries", "2 queries"),
        ],
    )
    def test_pluralize(self, count, singular, plural, expected) -> None:
        assert pluralize(count, singular, plural) == expected


class TestRegistration:
    """The built-in table is a set of defaults, not a fixed list."""

    def setup_method(self) -> None:
        from shipit_agent.narrate.verbs import registered_verbs, unregister_verb

        for name in registered_verbs():
            unregister_verb(name)

    teardown_method = setup_method

    def test_registering_an_unknown_tool(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verb

        register_verb(
            "deploy_service",
            VerbSpec("Shipped", "Shipping", "✚", noun="service", args=("service",)),
        )
        summary = summarize("deploy_service", {"service": "billing-api"})
        assert summary.past_label() == "Shipped billing-api"
        assert summary.present_label() == "Shipping billing-api"
        assert describe_count("deploy_service", 3) == "Shipped 3 services"

    def test_registration_overrides_a_builtin(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verb

        assert summarize("bash", {"command": "ls"}).past_label() == "Ran ls"
        register_verb(
            "bash", VerbSpec("Executed", "Executing", "❯", noun="command", args=("command",))
        )
        assert summarize("bash", {"command": "ls"}).past_label() == "Executed ls"

    def test_unregister_restores_the_builtin(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verb, unregister_verb

        register_verb("bash", VerbSpec("Executed", "Executing", "❯"))
        unregister_verb("bash")
        assert summarize("bash", {"command": "ls"}).past_label() == "Ran ls"

    def test_unregistering_something_absent_is_a_no_op(self) -> None:
        from shipit_agent.narrate.verbs import unregister_verb

        unregister_verb("never_registered")

    def test_bulk_registration(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verbs

        register_verbs(
            {
                "a_tool": VerbSpec("Aaa", "Aaaing", "◆"),
                "b_tool": VerbSpec("Bbb", "Bbbing", "◆"),
            }
        )
        assert summarize("a_tool", {}).past_label() == "Aaa"
        assert summarize("b_tool", {}).past_label() == "Bbb"

    def test_registered_verbs_returns_a_copy(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verb, registered_verbs

        register_verb("x_tool", VerbSpec("X", "Xing", "◆"))
        snapshot = registered_verbs()
        snapshot.clear()
        assert "x_tool" in registered_verbs()

    def test_non_spec_is_rejected(self) -> None:
        from shipit_agent.narrate.verbs import register_verb

        with pytest.raises(TypeError):
            register_verb("bad", {"past": "Did"})

    def test_registration_reaches_the_read_only_classification(self) -> None:
        from shipit_agent.narrate.verbs import VerbSpec, register_verb

        register_verb("peek_at_thing", VerbSpec("Peeked", "Peeking", "⌕", read_only=True))
        assert summarize("peek_at_thing", {}).read_only
