"""
14 — Cost tracking and budget enforcement.

``CostTracker`` prices each LLM call from a built-in model pricing table and
enforces a ``Budget``. Two safety behaviours are demonstrated:

1. A budget that is exceeded raises ``BudgetExceededError``.
2. An *unknown* model (absent from the pricing table) is no longer silently
   billed at $0.00 — with ``on_unknown_model="error"`` it raises, and with the
   default ``"warn"`` it flags ``tracker.has_unknown_pricing`` so a budget
   can't be silently bypassed.

Run:
    python examples/14_cost_budget.py
"""

from __future__ import annotations

from shipit_agent import Budget, BudgetExceededError, CostTracker


def main() -> None:
    print("─" * 60)
    print("  Cost tracking + budget enforcement")
    print("─" * 60)

    # 1. Normal accounting against a generous budget.
    tracker = CostTracker(budget=Budget(max_dollars=1.00))
    rec = tracker.record_call(
        "gpt-4o-mini", input_tokens=10_000, output_tokens=2_000
    )
    print(f"\n  Call 1 ({rec.model}): ${rec.cost_usd:.6f}")
    print(f"  Running total: ${tracker.total_cost:.6f}")

    # 2. A tight budget that gets exceeded → raises.
    tight = CostTracker(budget=Budget(max_dollars=0.0001))
    try:
        tight.record_call("gpt-4o", input_tokens=50_000, output_tokens=20_000)
    except BudgetExceededError as exc:
        print(f"\n  Budget guard tripped as expected: {exc}")

    # 3. Unknown model can't silently bypass the budget.
    strict = CostTracker(
        budget=Budget(max_dollars=1.00), on_unknown_model="error"
    )
    try:
        strict.record_call("some-unlisted-model-v9", 1000, 1000)
    except (ValueError, BudgetExceededError) as exc:
        print(f"\n  Unknown model rejected (no silent $0): {exc}")

    warn_tracker = CostTracker()  # default on_unknown_model="warn"
    warn_tracker.record_call("some-unlisted-model-v9", 1000, 1000)
    print(
        f"\n  has_unknown_pricing flag set: {warn_tracker.has_unknown_pricing} "
        "(reported cost is a lower bound)"
    )


if __name__ == "__main__":
    main()
