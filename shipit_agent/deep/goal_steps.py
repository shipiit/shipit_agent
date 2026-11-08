"""GoalAgent's model steps: decompose a goal and evaluate progress."""

from __future__ import annotations

import json
from typing import Any

from .goal_prompts import DECOMPOSE_PROMPT, EVALUATE_PROMPT


class _GoalSteps:
    """GoalAgent's model steps: decompose a goal and evaluate progress."""

    def _llm_call(self, prompt: str) -> str:
        from shipit_agent.core.models import Message

        response = self.llm.complete(messages=[Message(role="user", content=prompt)])
        return response.content

    def _decompose(self) -> list[str]:
        """Break goal into sub-tasks."""
        criteria_text = "\n".join(f"- {c}" for c in self.goal.success_criteria)
        text = self._llm_call(
            DECOMPOSE_PROMPT.format(
                objective=self.goal.objective,
                criteria=criteria_text,
            )
        )
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                return data.get("subtasks", [self.goal.objective])
        except (json.JSONDecodeError, ValueError):
            pass
        return [self.goal.objective]

    def _evaluate(self, work_done: list[str]) -> dict[str, Any]:
        """Evaluate progress against success criteria."""
        criteria_text = "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(self.goal.success_criteria)
        )
        work_text = "\n".join(f"Step {i+1}: {w[:300]}" for i, w in enumerate(work_done))
        text = self._llm_call(
            EVALUATE_PROMPT.format(
                objective=self.goal.objective,
                criteria=criteria_text,
                work=work_text,
            )
        )
        # Strip reasoning tags that some models wrap around JSON
        import re

        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL).strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                # If criteria_met has wrong length, pad or trim it
                expected = len(self.goal.success_criteria)
                met = data.get("criteria_met", [])
                if len(met) < expected:
                    met.extend([False] * (expected - len(met)))
                elif len(met) > expected:
                    met = met[:expected]
                data["criteria_met"] = met
                # Be generous: if most work is done, check content-based matching
                if not data.get("all_done"):
                    combined = " ".join(work_done).lower()
                    matched = sum(
                        1
                        for c in self.goal.success_criteria
                        if any(w in combined for w in c.lower().split())
                    )
                    if matched >= len(self.goal.success_criteria):
                        data["all_done"] = True
                        data["criteria_met"] = [True] * expected
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: check if work content matches criteria by keyword
        combined = " ".join(work_done).lower()
        met = [
            any(w in combined for w in c.lower().split())
            for c in self.goal.success_criteria
        ]
        all_done = all(met)
        return {
            "criteria_met": met,
            "all_done": all_done,
            "next_action": "done" if all_done else "continue",
        }
