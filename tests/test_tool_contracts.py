"""Tool contracts — every tool declares what it is instead of being guessed."""

from __future__ import annotations

import pytest

from shipit_agent.builtins import get_builtin_tools
from shipit_agent.permissions import PermissionEngine
from shipit_agent.tools.contracts import (
    CONTRACTS,
    OBSERVE,
    ActionKind,
    ToolContract,
    action_kinds,
    contract_for,
    register_contract,
    register_contracts,
    registered_contracts,
    unregister_contract,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    for name in registered_contracts():
        unregister_contract(name)
    yield
    for name in registered_contracts():
        unregister_contract(name)


class TestCoverage:
    def test_every_builtin_has_a_contract(self) -> None:
        names = {
            getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")
        }
        assert not names - set(CONTRACTS), "builtins missing a ToolContract"

    def test_no_contract_exists_for_a_tool_that_does_not(self) -> None:
        names = {
            getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")
        }
        # Opt-in tools are real but not in the default catalogue — execute_code
        # needs the code-mode gate published into tool state, so shipping it by
        # default would only ever answer "code mode is not enabled".
        opt_in = {"execute_code"}
        assert not set(CONTRACTS) - names - opt_in, "contract for a nonexistent tool"

    def test_opt_in_tools_are_importable(self) -> None:
        from shipit_agent.tools.execute_code import ExecuteCodeTool

        assert ExecuteCodeTool().name == "execute_code"

    def test_every_action_declares_a_kind_or_is_permanently_manual(self) -> None:
        for name, contract in CONTRACTS.items():
            if contract.is_action and contract.action_kind is None:
                # Allowed, but it means this tool can never be auto-approved.
                assert not contract.auto_approvable, name

    def test_action_kind_tags_are_namespaced(self) -> None:
        for kind in action_kinds():
            assert "." in kind.tag, f"{kind.tag} should be 'domain.verb'"
            assert kind.label and kind.label[0].isupper()


class TestInvariants:
    def test_auto_approvable_requires_a_kind(self) -> None:
        with pytest.raises(ValueError, match="action_kind"):
            ToolContract(auto_approvable=True)

    def test_destructive_cannot_be_auto_approvable(self) -> None:
        with pytest.raises(ValueError, match="destructive"):
            ToolContract(
                action_kind=ActionKind("x.y", "X"),
                auto_approvable=True,
                destructive=True,
            )

    def test_no_builtin_violates_the_invariants(self) -> None:
        # Construction already enforces them; this pins that the table loaded.
        assert CONTRACTS
        for contract in CONTRACTS.values():
            if contract.auto_approvable:
                assert contract.action_kind is not None
                assert not contract.destructive


class TestJudgement:
    """The specific calls a reviewer should challenge."""

    def test_execution_tools_are_never_auto_approvable(self) -> None:
        # The argument is arbitrary code, so the tag says nothing about risk.
        for name in ("bash", "run_code", "sql"):
            assert not CONTRACTS[name].auto_approvable, name
            assert CONTRACTS[name].destructive, name

    def test_execution_tools_make_the_agent_wait(self) -> None:
        for name in ("bash", "run_code", "sql"):
            assert CONTRACTS[name].await_decision, name

    def test_fire_and_forget_sends_do_not_block_the_agent(self) -> None:
        # "Queued" is the whole result; there is nothing to reason over.
        assert not CONTRACTS["slack"].await_decision
        assert not CONTRACTS["jira"].await_decision

    def test_asking_a_human_is_an_observation(self) -> None:
        # It is the approval channel; gating it would deadlock.
        for name in ("ask_user", "ask_user_async", "human_review"):
            assert CONTRACTS[name].read_only, name

    def test_pure_reasoning_tools_are_observations(self) -> None:
        for name in ("plan_task", "decompose_problem", "decision_matrix"):
            assert CONTRACTS[name].read_only, name

    def test_file_edits_are_revertible_and_pre_approvable(self) -> None:
        for name in ("write_file", "edit_file"):
            assert CONTRACTS[name].implements_revert, name
            assert CONTRACTS[name].auto_approvable, name

    def test_money_is_destructive(self) -> None:
        assert CONTRACTS["stripe"].destructive
        assert not CONTRACTS["stripe"].auto_approvable

    def test_send_actions_share_one_tag(self) -> None:
        # A user answering "always approve sending?" answers once, not per app.
        assert CONTRACTS["slack"].tag == CONTRACTS["zendesk"].tag == "comms.send"


class TestResolution:
    def test_builtin_table_is_used(self) -> None:
        assert contract_for("read_file").read_only
        assert not contract_for("bash").read_only

    def test_registration_overrides_the_table(self) -> None:
        register_contract("bash", OBSERVE)
        assert contract_for("bash").read_only

    def test_tool_object_declaration_beats_a_registration(self) -> None:
        class Declared:
            read_only = True

        register_contract("thing", ToolContract(action_kind=ActionKind("a.b", "B")))
        assert contract_for("thing", Declared()).read_only

    def test_a_whole_contract_on_the_tool_is_used(self) -> None:
        kind = ActionKind("deploy.write", "Deploy")

        class Declared:
            contract = ToolContract(action_kind=kind, destructive=True)

        resolved = contract_for("deploy_it", Declared())
        assert resolved.action_kind == kind
        assert resolved.destructive

    def test_loose_attributes_on_a_tool_are_honoured(self) -> None:
        kind = ActionKind("x.write", "X")

        class Declared:
            read_only = False
            action_kind = kind
            implements_revert = True

        resolved = contract_for("x_tool", Declared())
        assert resolved.action_kind == kind
        assert resolved.implements_revert

    def test_unknown_read_only_looking_tool_falls_back_cleanly(self) -> None:
        assert contract_for("list_widgets").read_only

    def test_unknown_mutating_tool_is_gated_and_untagged(self) -> None:
        contract = contract_for("widget_delete")
        assert contract.is_action
        # Untagged means it can never match an auto-approval rule.
        assert contract.action_kind is None
        assert not contract.auto_approvable
        assert contract.await_decision

    def test_bulk_registration(self) -> None:
        register_contracts({"a": OBSERVE, "b": OBSERVE})
        assert contract_for("a").read_only and contract_for("b").read_only

    def test_registered_contracts_returns_a_copy(self) -> None:
        register_contract("a", OBSERVE)
        registered_contracts().clear()
        assert "a" in registered_contracts()

    def test_non_contract_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            register_contract("a", {"read_only": True})

    def test_contract_for_never_raises(self) -> None:
        for name in ("", "___", "a" * 300, "тест", "server__weird__name"):
            assert contract_for(name) is not None


class TestPermissionEngineIntegration:
    def test_engine_reads_declared_contracts(self) -> None:
        # `figma` matches no read-only or mutating glob; only the contract
        # tells the engine it mutates.
        assert not PermissionEngine().is_read_only("figma")

    def test_declared_observation_beats_a_mutating_glob(self) -> None:
        # "plan_task" is read-only by contract; confirm the engine agrees.
        assert PermissionEngine().is_read_only("plan_task")

    def test_registration_reaches_the_engine(self) -> None:
        register_contract("bash", OBSERVE)
        assert PermissionEngine().is_read_only("bash")

    def test_tool_attribute_still_wins_over_a_contract(self) -> None:
        class Declared:
            read_only = True

        assert PermissionEngine().is_read_only("bash", Declared())

    def test_globs_still_apply_to_undeclared_tools(self) -> None:
        engine = PermissionEngine()
        assert engine.is_read_only("get_thing")
        assert not engine.is_read_only("thing_delete")

    def test_plan_mode_allows_every_declared_observation(self) -> None:
        engine = PermissionEngine(mode="plan")
        for name, contract in CONTRACTS.items():
            if contract.read_only:
                assert engine.check(name, {}).allowed, name

    def test_plan_mode_denies_every_declared_action(self) -> None:
        engine = PermissionEngine(mode="plan")
        for name, contract in CONTRACTS.items():
            if contract.is_action:
                assert engine.check(name, {}).denied, name


class TestNarratorAgreement:
    def test_contracts_and_verb_specs_agree_on_read_only(self) -> None:
        """Two tables, one truth — a disagreement is a rendering bug."""
        from shipit_agent.narrate.verbs import VERBS

        mismatched = [
            name
            for name, contract in CONTRACTS.items()
            if name in VERBS and VERBS[name].read_only != contract.read_only
        ]
        assert not mismatched, f"read_only disagreement: {mismatched}"


class TestAllowListingPattern:
    """`deny=["*"]` is a trap: deny outranks allow, so it denies everything."""

    def test_a_wildcard_deny_also_denies_allow_listed_tools(self) -> None:
        engine = PermissionEngine(allow=["read_file"], deny=["*"])
        assert engine.check("read_file", {}).denied

    def test_the_correct_way_to_mean_these_and_nothing_else(self) -> None:
        from shipit_agent.permissions import PermissionDecision

        engine = PermissionEngine(
            allow=["read_file", "grep_files"],
            default_decision=PermissionDecision.DENY,
        )
        assert engine.check("read_file", {}).allowed
        assert engine.check("grep_files", {}).allowed
        assert engine.check("bash", {}).denied
        assert engine.check("write_file", {}).denied
