"""Automatic delegation — when the agent reaches for sub-agents unprompted."""

from __future__ import annotations

import pytest

from shipit_agent import Agent
from shipit_agent.delegation import (
    DelegationPolicy,
    ModelAssessor,
    StructuralAssessor,
    coerce_delegation,
)
from shipit_agent.llms.base import LLMResponse


class FakeLLM:
    model = "fake"

    def complete(self, **kwargs):
        return LLMResponse(content="ok", usage={})


class Reader:
    name = "read_file"
    description = "Read a file."
    prompt_instructions = ""

    def schema(self):
        return {"type": "function", "function": {"name": self.name}}


class Writer:
    name = "write_file"
    description = "Write a file."
    prompt_instructions = ""

    def schema(self):
        return {"type": "function", "function": {"name": self.name}}


class TestStructural:
    """Counts structure — lists, targets, quantities. Never vocabulary."""

    def test_an_enumerated_list_counts_as_items(self) -> None:
        advice = StructuralAssessor().assess(
            "Look at:\n1. auth.py\n2. views.py\n3. models.py\n4. urls.py"
        )
        assert advice and advice.items >= 4

    def test_named_targets_count(self) -> None:
        advice = StructuralAssessor().assess("Compare a.py, b.py and c.py")
        assert advice.items == 3

    def test_a_stated_quantity_counts(self) -> None:
        assert StructuralAssessor().assess(
            "Summarize the twelve incident reports"
        ).items == 12
        assert StructuralAssessor().assess("Review 8 pull requests").items == 8

    def test_one_target_is_not_a_fan_out(self) -> None:
        assert not StructuralAssessor().assess("Read config.yaml and tell me the port")

    def test_an_empty_task_is_not(self) -> None:
        assert not StructuralAssessor().assess("")

    def test_it_works_in_any_language(self) -> None:
        """No word list, so a non-English task still assesses."""
        assert StructuralAssessor().assess(
            "Resume cada informe:\n- a.md\n- b.md\n- c.md"
        ).items >= 3


class TestPolicyThresholds:
    def test_the_threshold_is_configurable(self) -> None:
        prompt = "Read a.py and b.py"
        assessor = StructuralAssessor()
        assert not DelegationPolicy(min_items=3, assessor=assessor).assess(prompt)
        assert DelegationPolicy(min_items=2, assessor=assessor).assess(prompt)

    def test_a_disabled_policy_never_advises(self) -> None:
        assert not DelegationPolicy(enabled=False).assess("a.py b.py c.py")

    def test_the_reason_is_reported_not_just_the_verdict(self) -> None:
        advice = DelegationPolicy(assessor=StructuralAssessor()).assess(
            "Summarize a.md, b.md and c.md"
        )
        assert advice.reasons and all(isinstance(r, str) for r in advice.reasons)


class TestDirective:
    def test_it_names_what_was_detected(self) -> None:
        policy = DelegationPolicy(assessor=StructuralAssessor())
        text = policy.directive(policy.assess("Summarize a.md, b.md and c.md"))
        assert "sub_agent" in text
        assert "concrete targets" in text

    def test_no_directive_for_a_narrow_task(self) -> None:
        policy = DelegationPolicy(assessor=StructuralAssessor())
        assert policy.directive(policy.assess("What is in guests.csv?")) == ""

    def test_it_tells_the_agent_to_combine_the_results_itself(self) -> None:
        policy = DelegationPolicy(assessor=StructuralAssessor())
        text = policy.directive(policy.assess("Check a.py, b.py and c.py"))
        assert "do not delegate the combining" in text

    def test_apply_lands_the_directive_on_the_task(self) -> None:
        policy = DelegationPolicy(assessor=StructuralAssessor())
        task = "Summarize a.md, b.md and c.md"
        assert policy.apply(task).startswith(task)
        assert "sub_agent" in policy.apply(task)


#: A task the policy agrees is separable — these tests are about attaching
#: and pooling the tool, not about whether it should be attached.
SEPARABLE = "Audit all 5 reports and summarise each one."


class TestToolAttachment:
    def test_a_sub_agent_appears_when_the_agent_has_none(self) -> None:
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        names = {getattr(t, "name", "")
                 for t in agent._effective_tools(SEPARABLE)}
        assert "sub_agent" in names

    def test_it_is_absent_for_a_narrow_task(self) -> None:
        """The toolbox matches the advice.

        This used to be the other way round — the tool was attached on every
        turn on the reasoning that a model deciding mid-run to delegate must
        find it there. Measured against Gemma 4, that reasoning fails: asked
        "look for the latest AI news", it spawned three research children
        rather than running one web search. A tool on the table gets used,
        and a weaker model reaches for the most impressive one. The policy
        already judges each task for the directive; the tool follows it.
        """
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        names = {getattr(t, "name", "") for t in agent._effective_tools("Read a.py")}
        assert "sub_agent" not in names

    def test_an_explicit_sub_agent_tool_is_never_withheld(self) -> None:
        """Only what `delegation=` injects is conditional. A caller who
        passed the tool made a decision, and this must not override it."""
        from shipit_agent.tools.sub_agent import SubAgentTool

        agent = Agent(llm=FakeLLM(), tools=[Reader(), SubAgentTool(llm=FakeLLM())],
                      auto_use_skills=False)
        names = {getattr(t, "name", "") for t in agent._effective_tools("Read a.py")}
        assert "sub_agent" in names

    def test_no_tool_without_the_flag(self) -> None:
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False)
        names = {getattr(t, "name", "") for t in agent._effective_tools("Audit all.")}
        assert "sub_agent" not in names

    def test_the_pool_is_built_once_per_agent(self) -> None:
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        first = {t.name: t
                 for t in agent._effective_tools(SEPARABLE)}["sub_agent"]
        second = {t.name: t
                  for t in agent._effective_tools(SEPARABLE)}["sub_agent"]
        assert first is second, "a thread pool per run would leak one per run"

    def test_an_explicit_sub_agent_is_not_replaced(self) -> None:
        from shipit_agent.tools.sub_agent import SubAgentTool

        mine = SubAgentTool(llm=FakeLLM(), max_iterations=2)
        agent = Agent(llm=FakeLLM(), tools=[Reader(), mine], auto_use_skills=False,
                      delegation=True)
        tools = {getattr(t, "name", ""): t
                 for t in agent._effective_tools(SEPARABLE)}
        assert tools["sub_agent"] is mine

    def test_children_get_read_only_tools_by_default(self) -> None:
        """A sub-agent that can write is a side effect nobody reviewed."""
        policy = DelegationPolicy()
        tool = policy.build_tool(FakeLLM(), [Reader(), Writer()])
        assert [t.name for t in tool.tools] == ["read_file"]

    def test_children_can_be_given_an_explicit_toolset(self) -> None:
        writer = Writer()
        tool = DelegationPolicy(child_tools=[writer]).build_tool(
            FakeLLM(), [Reader()]
        )
        assert tool.tools == [writer]

    def test_attachment_can_be_declined(self) -> None:
        assert DelegationPolicy(attach_tool=False).build_tool(FakeLLM(), []) is None

    def test_no_llm_means_no_sub_agent(self) -> None:
        assert DelegationPolicy().build_tool(None, []) is None


class TestPromptIntegration:
    """The directive rides on the task, not the system prompt — measured."""

    @staticmethod
    def _agent(**kwargs):
        return Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                     max_iterations=2, **kwargs)

    def test_the_directive_reaches_the_task(self) -> None:
        agent = self._agent(
            delegation=DelegationPolicy(assessor=StructuralAssessor())
        )
        assert "sub_agent" in agent._delegated_prompt("Summarize a.md, b.md, c.md")

    def test_the_system_prompt_is_left_alone(self) -> None:
        agent = self._agent(
            delegation=DelegationPolicy(assessor=StructuralAssessor())
        )
        assert "sub_agent`," not in agent._effective_prompt("Summarize a.md, b.md")

    def test_a_narrow_task_is_passed_through_untouched(self) -> None:
        agent = self._agent(
            delegation=DelegationPolicy(assessor=StructuralAssessor())
        )
        assert agent._delegated_prompt("Read a.py") == "Read a.py"

    def test_the_task_is_untouched_without_the_flag(self) -> None:
        agent = self._agent()
        task = "Summarize a.md, b.md and c.md"
        assert agent._delegated_prompt(task) == task

    def test_a_run_still_works_end_to_end(self) -> None:
        agent = self._agent(
            delegation=DelegationPolicy(assessor=StructuralAssessor())
        )
        assert agent.run("Summarize a.md, b.md and c.md").output == "ok"


class TestCoercion:
    def test_true_means_the_defaults(self) -> None:
        assert isinstance(coerce_delegation(True), DelegationPolicy)

    def test_none_and_false_mean_off(self) -> None:
        assert coerce_delegation(None) is None
        assert coerce_delegation(False) is None

    def test_a_disabled_policy_is_off(self) -> None:
        assert coerce_delegation(DelegationPolicy(enabled=False)) is None

    def test_a_dict_configures_it(self) -> None:
        assert coerce_delegation({"min_items": 7}).min_items == 7

    def test_nonsense_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            coerce_delegation(3.5)


class TestModelAssessor:
    """The default: ask the model, and survive every way it can answer."""

    class Replying:
        def __init__(self, content: str) -> None:
            self.content = content
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            return LLMResponse(content=self.content, usage={})

    class Exploding:
        def complete(self, **kwargs):
            raise RuntimeError("provider down")

    def test_a_clean_verdict_is_used(self) -> None:
        llm = self.Replying('{"decompose": true, "items": 9, "reason": "nine repos"}')
        advice = ModelAssessor().assess("Check a.py, b.py and c.py", llm=llm)
        assert advice and advice.items == 9
        assert advice.reasons == ["nine repos"]
        assert advice.source == "model"

    def test_a_fenced_verdict_is_still_read(self) -> None:
        llm = self.Replying(
            'Sure!\n```json\n{"decompose": true, "items": 4, "reason": "four"}\n```'
        )
        assert ModelAssessor().assess("Read a.py, b.py", llm=llm).items == 4

    def test_an_invented_decomposition_is_overruled(self) -> None:
        """Gemma 4, asked "Can you look for the latest AI news?", answered
        `decompose: true, items: 3, "news can be split by topic or source"`
        — three agents for one search, and not one of those topics appears
        in the request. Almost any task *could* be split; a yes has to be
        corroborated by something actually in the text."""
        llm = self.Replying(
            '{"decompose": true, "items": 3, "reason": "split by topic"}')
        advice = ModelAssessor().assess(
            "Can you look for the latest AI news?", llm=llm)
        assert not advice
        assert "names no separable pieces" in advice.reasons[0]

    def test_the_count_it_saw_is_still_reported(self) -> None:
        """Overruled, not erased — the number is what someone asking "why
        did it not delegate" needs to see."""
        llm = self.Replying(
            '{"decompose": true, "items": 3, "reason": "split by topic"}')
        assert ModelAssessor().assess("Find the news", llm=llm).items == 3

    def test_a_refusal_to_decompose_is_honoured(self) -> None:
        llm = self.Replying('{"decompose": false, "items": 0, "reason": "one edit"}')
        assert not ModelAssessor().assess("Fix the typo", llm=llm)

    def test_unparseable_output_falls_back_to_structure(self) -> None:
        llm = self.Replying("I think you should probably split it up?")
        advice = ModelAssessor().assess("Read a.py, b.py and c.py", llm=llm)
        assert advice and advice.source == "structural"

    def test_a_dead_provider_never_blocks_the_run(self) -> None:
        advice = ModelAssessor().assess("Read a.py and b.py", llm=self.Exploding())
        assert advice.source == "structural"

    def test_no_model_means_structure_only(self) -> None:
        assert ModelAssessor().assess("Read a.py, b.py, c.py").source == "structural"

    def test_structure_overrules_an_undercount(self) -> None:
        """The task names four files; a model saying "one piece" is wrong."""
        llm = self.Replying('{"decompose": false, "items": 1, "reason": "small"}')
        advice = ModelAssessor().assess("Read a.py, b.py, c.py, d.py", llm=llm)
        assert advice.items == 4
        assert advice, "four named files is a fan-out whatever the model says"

    def test_the_verdict_is_cached_per_task(self) -> None:
        llm = self.Replying('{"decompose": true, "items": 3, "reason": "three"}')
        assessor = ModelAssessor()
        for _ in range(4):
            assessor.assess("same task", llm=llm)
        assert llm.calls == 1, "sizing a task should cost one call, not one per run"

    def test_it_is_the_default_assessor(self) -> None:
        assert isinstance(DelegationPolicy().assessor, ModelAssessor)


class TestTheToolboxMatchesTheAdvice:
    """Observed on Gemma 4: asked "Can you look for the latest AI news?",
    the agent spawned three research sub-agents instead of running one web
    search. `delegation=` was attaching `sub_agent` on every turn, and a
    tool on the table gets used.
    """

    def test_a_one_step_question_gets_no_sub_agent(self) -> None:
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        names = {getattr(t, "name", "")
                 for t in agent._effective_tools(
                     "Can you look for the latest AI news?")}
        assert "sub_agent" not in names

    def test_a_separable_task_still_gets_one(self) -> None:
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        names = {getattr(t, "name", "")
                 for t in agent._effective_tools(
                     "Read all 4 reports and summarise each one.")}
        assert "sub_agent" in names

    def test_the_tool_and_the_directive_agree(self) -> None:
        """A directive telling the model to delegate, with no tool to
        delegate with, is the failure this pairing prevents."""
        agent = Agent(llm=FakeLLM(), tools=[Reader()], auto_use_skills=False,
                      delegation=True)
        for task in ("Read a.py",
                     "Read all 4 reports and summarise each one."):
            attached = "sub_agent" in {
                getattr(t, "name", "") for t in agent._effective_tools(task)}
            directed = agent._delegated_prompt(task) != task
            assert attached == directed, task


class TestBreadth:
    """"Go through every document attached" names no number and no
    filename, and is exactly the work worth splitting. Counting lists,
    targets and quantities missed it, so the corroboration floor added in
    1.3.2 would have declined it too.

    The signal is grammar, not vocabulary: a distributive determiner over a
    noun. That holds for wording nobody anticipated, which a keyword list
    does not.
    """

    def assess(self, prompt: str):
        from shipit_agent.delegation import StructuralAssessor

        return StructuralAssessor().assess(prompt)

    def test_every_over_a_set_counts(self) -> None:
        assert self.assess("Go through every document attached.")

    def test_each_of_counts(self) -> None:
        assert self.assess("Audit each of our repos for exposed secrets.")

    def test_all_the_counts(self) -> None:
        assert self.assess("Review all the open PRs and flag risky ones.")

    def test_the_count_is_not_invented(self) -> None:
        """Breadth says "more than one", not how many. Guessing a number
        here would feed a fake quantity to the min_items filter."""
        assert self.assess("Check every service.").items == 0

    def test_an_adverbial_all_is_not_breadth(self) -> None:
        for phrase in ("Is it all good?", "Tell me all about it.",
                       "Is that all right?"):
            assert not self.assess(phrase), phrase

    def test_a_single_thing_is_still_a_single_thing(self) -> None:
        for phrase in ("Fix the typo.", "Summarise this file.",
                       "Can you look for the latest AI news?"):
            assert not self.assess(phrase), phrase
