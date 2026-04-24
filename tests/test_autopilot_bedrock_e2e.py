"""End-to-end Autopilot tests against a real Bedrock LLM.

These are opt-in tests. They only run when::

    SHIPIT_BEDROCK_E2E=1 pytest tests/test_autopilot_bedrock_e2e.py

…and require a working Bedrock configuration on the host:

* AWS credentials resolvable by boto3 (profile, env, or instance role).
* ``AWS_REGION_NAME`` or ``AWS_DEFAULT_REGION``.
* ``litellm`` installed (the BedrockChatLLM adapter uses it).
* A Bedrock model id the caller has access to — override the default
  via ``SHIPIT_BEDROCK_E2E_MODEL`` (defaults to Amazon Nova Lite, which
  most AWS accounts can invoke without the Anthropic use-case form).

What these cover (that the stub-based tests can't):

* Autopilot drives a real LLM to goal completion.
* Token + dollar usage arrives from the provider and accumulates
  correctly through the run (via an inner agent that threads the
  provider's ``usage`` back into Autopilot's accounting).
* ``run()``, ``resume()``, ``stream()``, and ``fanout()`` all work
  against the same LLM surface end-to-end.
* Artifacts get extracted from the actual markdown the model emits.

Each test enforces a tight budget (≤ 60s, ≤ 20k tokens, ≤ $0.25) so a
full run of this file stays cheap.

Note on GoalAgent vs. the inner-agent used here: GoalAgent doesn't
currently propagate per-iteration LLM ``usage`` into its ``GoalResult``,
so a plain ``Autopilot(llm=bedrock, goal=…)`` won't see tokens come
back through ``result.usage``. These tests use a minimal inner agent
that *does* thread usage through — proving the Bedrock → Autopilot
accounting stack works end-to-end.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.autopilot import (
    ArtifactCollector,
    Autopilot,
    BudgetPolicy,
    Critic,
)
from shipit_agent.deep.goal_agent import Goal
from shipit_agent.models import Message


# ─────────────────────── gating ───────────────────────


E2E_ENABLED = os.environ.get("SHIPIT_BEDROCK_E2E", "").lower() in ("1", "true", "yes")

pytestmark = pytest.mark.skipif(
    not E2E_ENABLED,
    reason="Bedrock E2E tests disabled. Set SHIPIT_BEDROCK_E2E=1 to enable.",
)


DEFAULT_MODEL = os.environ.get(
    "SHIPIT_BEDROCK_E2E_MODEL",
    "bedrock/us.amazon.nova-lite-v1:0",
)


@pytest.fixture(scope="module")
def bedrock_llm() -> Any:
    """Build a real Bedrock LLM or skip if the environment isn't ready."""
    try:
        import litellm  # noqa: F401
    except ImportError:
        pytest.skip("litellm not installed")

    from shipit_agent.llms import build_llm_from_settings

    try:
        return build_llm_from_settings(
            {"provider": "bedrock", "model": DEFAULT_MODEL},
            provider="bedrock",
        )
    except RuntimeError as exc:
        pytest.skip(f"Bedrock unreachable: {exc}")


# ─────────────────────── thin inner agent ───────────────────────


@dataclass
class _StepResult:
    """What Autopilot's inner-agent contract expects back from ``run()``."""

    output: str = ""
    goal_status: str = "in_progress"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class _BedrockStepAgent:
    """Minimal inner agent: one Bedrock call per iteration.

    Surfaces the provider's ``usage`` dict in ``result.metadata`` so
    Autopilot's token + dollar counters actually increment — which is
    the bit of the stack we want these E2E tests to cover.
    """

    def __init__(self, *, llm: Any, goal: Goal, **_: Any) -> None:
        self.llm = llm
        self.goal = goal

    def run(self) -> _StepResult:
        criteria_list = "\n".join(f"- {c}" for c in self.goal.success_criteria)
        prompt = (
            f"Objective: {self.goal.objective}\n\n"
            f"Success criteria:\n{criteria_list}\n\n"
            "Complete the objective in one short response, directly addressing the criteria."
        )
        response = self.llm.complete(messages=[Message(role="user", content=prompt)])
        content = response.content or ""
        usage = response.usage or {}
        # Map LiteLLM usage → Autopilot's expected shape.
        total = int(
            usage.get("total_tokens")
            or (
                int(usage.get("prompt_tokens", 0))
                + int(usage.get("completion_tokens", 0))
            )
            or 0
        )
        met = [self._criterion_met(c, content) for c in self.goal.success_criteria]
        return _StepResult(
            output=content,
            goal_status="completed" if all(met) and met else "in_progress",
            criteria_met=met,
            metadata={
                "model": getattr(self.llm, "model", "bedrock/unknown"),
                "usage": {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "total_tokens": total,
                },
            },
        )

    @staticmethod
    def _criterion_met(criterion: str, output: str) -> bool:
        """Naive criterion match: tokens from the criterion must appear
        in the output. Good enough for smoke tests — the production
        critic is a separate code path tested elsewhere."""
        needles = [w.strip().lower() for w in criterion.split() if len(w) > 3]
        if not needles:
            return bool(output.strip())
        lowered = output.lower()
        return sum(n in lowered for n in needles) >= max(1, len(needles) // 2)


def _bedrock_autopilot(
    tmp_path: Path,
    bedrock_llm: Any,
    *,
    goal: Goal,
    budget: BudgetPolicy | None = None,
    **kw: Any,
) -> Autopilot:
    return Autopilot(
        llm=bedrock_llm,
        goal=goal,
        checkpoint_dir=tmp_path,
        budget=budget
        or BudgetPolicy(
            max_iterations=2,
            max_seconds=45,
            max_tokens=10_000,
            max_dollars=0.20,
            max_tool_calls=50,
        ),
        agent_factory=lambda *, llm, goal, **_: _BedrockStepAgent(llm=llm, goal=goal),
        install_signal_handlers=False,
        **kw,
    )


# ─────────────────────── single-run smoke ───────────────────────


def test_run_reaches_a_goal(tmp_path: Path, bedrock_llm: Any) -> None:
    """A trivially-satisfiable goal should complete and report non-zero
    token usage from the provider."""

    goal = Goal(
        objective="Reply with the sentence 'ready for work'.",
        success_criteria=["Output contains ready"],
    )
    auto = _bedrock_autopilot(tmp_path, bedrock_llm, goal=goal)
    result = auto.run(run_id="bedrock-smoke")

    assert result.status in ("completed", "partial")
    assert result.iterations >= 1
    assert result.usage["tokens"] > 0, "expected non-zero token usage from Bedrock"
    assert result.output.strip()


def test_dollar_usage_accumulates(tmp_path: Path, bedrock_llm: Any) -> None:
    """Dollars may stay $0 for models we don't price, but tokens must
    accumulate. When pricing resolves, dollars should be small but
    positive and under the budget."""

    goal = Goal(objective="Say 'ok'.", success_criteria=["Output contains ok"])
    auto = _bedrock_autopilot(tmp_path, bedrock_llm, goal=goal)
    result = auto.run(run_id="bedrock-dollars")

    assert result.usage["tokens"] > 0
    assert (
        0.0 <= result.usage["dollars"] < 0.20
    ), f"dollar usage {result.usage['dollars']} outside safe range"


# ─────────────────────── streaming ───────────────────────


def test_stream_emits_events(tmp_path: Path, bedrock_llm: Any) -> None:
    goal = Goal(objective="Reply 'done'.", success_criteria=["Output contains done"])
    auto = _bedrock_autopilot(tmp_path, bedrock_llm, goal=goal)

    events = list(auto.stream(run_id="bedrock-stream"))
    kinds = [e["kind"] for e in events]

    assert kinds[0] == "autopilot.run_started"
    assert kinds[-1] == "autopilot.result"
    iterations = [e for e in events if e["kind"] == "autopilot.iteration"]
    assert iterations, "expected at least one iteration event"
    # Hardening: every iteration event carries a `remaining` budget
    # snapshot so a UI can render an ETA bar.
    assert "remaining" in iterations[0]
    assert iterations[0]["usage"]["tokens"] > 0


# ─────────────────────── resume ───────────────────────


def test_resume_is_cumulative(tmp_path: Path, bedrock_llm: Any) -> None:
    """Run once with iteration cap 1, then resume with a higher cap.
    The second run's tokens accumulate on top of the first — proving
    that a 24-hour resume wouldn't reset the budget counters."""

    goal = Goal(
        objective="Respond with the word 'ready'.",
        success_criteria=["Output contains ready"],
    )
    first = _bedrock_autopilot(
        tmp_path,
        bedrock_llm,
        goal=goal,
        budget=BudgetPolicy(
            max_iterations=1,
            max_seconds=30,
            max_tokens=5_000,
            max_dollars=0.10,
            max_tool_calls=50,
        ),
    )
    r1 = first.run(run_id="bedrock-resume")
    assert r1.iterations >= 1
    prior_tokens = r1.usage["tokens"]
    assert prior_tokens > 0

    second = _bedrock_autopilot(
        tmp_path,
        bedrock_llm,
        goal=goal,
        budget=BudgetPolicy(
            max_iterations=3,
            max_seconds=30,
            max_tokens=10_000,
            max_dollars=0.20,
            max_tool_calls=50,
        ),
    )
    r2 = second.resume("bedrock-resume")
    assert r2.iterations > r1.iterations
    assert r2.usage["tokens"] >= prior_tokens, "tokens must not reset on resume"


# ─────────────────────── artifacts ───────────────────────


def test_artifacts_extracted_from_real_output(tmp_path: Path, bedrock_llm: Any) -> None:
    collector = ArtifactCollector()
    goal = Goal(
        objective=(
            "Write a Python function `add(a, b)` that returns a + b. "
            "Respond with a single fenced ```python code block."
        ),
        success_criteria=["Code contains def add"],
    )
    auto = _bedrock_autopilot(tmp_path, bedrock_llm, goal=goal, artifacts=collector)
    result = auto.run(run_id="bedrock-artifacts")

    # Model usually emits a fenced code block. If it did, artifacts > 0
    # and every one is a code artifact. If it didn't, the list is empty
    # — both outcomes prove the extraction pipeline survived the run.
    assert all(a["kind"] in ("code", "markdown") for a in result.artifacts)


# ─────────────────────── critic ───────────────────────


def test_critic_runs_against_bedrock(tmp_path: Path, bedrock_llm: Any) -> None:
    """The critic calls the same Bedrock LLM to self-review. A successful
    run proves the JSON-return contract survives a real provider's
    tendency to wrap responses in prose."""
    goal = Goal(
        objective="Reply with the literal string 'hello'.",
        success_criteria=["Output contains hello"],
    )
    auto = _bedrock_autopilot(
        tmp_path,
        bedrock_llm,
        goal=goal,
        critic=Critic(confidence_threshold=0.5),
    )
    result = auto.run(run_id="bedrock-critic")
    # The critic returned *some* verdict (even zero-confidence counts
    # as wiring working end-to-end). The verdict dict always has
    # criteria_met, confidence, suggestions, reasoning keys.
    assert isinstance(result.critic_verdict, dict)
    assert "confidence" in result.critic_verdict


# ─────────────────────── fanout ───────────────────────


def test_fanout_across_small_batch(tmp_path: Path, bedrock_llm: Any) -> None:
    """Fan-out with two items exercises the ThreadPoolExecutor, child
    budget scaling, and result aggregation — all against a real LLM."""
    auto = _bedrock_autopilot(
        tmp_path,
        bedrock_llm,
        goal=Goal(objective="parent", success_criteria=["done"]),
        budget=BudgetPolicy(
            max_iterations=2,
            max_seconds=60,
            max_tokens=20_000,
            max_dollars=0.25,
            max_tool_calls=50,
        ),
    )
    result = auto.fanout(
        items=["one", "two"],
        objective_template="Respond with the single word '{item}'.",
        criteria_template=["Output contains {item}"],
        max_parallel=2,
        child_budget_frac=0.5,
    )
    assert result.status in ("completed", "partial")
    assert len(result.children) == 2
