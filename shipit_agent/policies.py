from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetryPolicy:
    max_llm_retries: int = 2
    max_tool_retries: int = 1
    retry_on_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: (ConnectionError, TimeoutError, OSError)
    )


@dataclass(slots=True)
class RouterPolicy:
    auto_plan: bool = True
    plan_keywords: tuple[str, ...] = (
        "plan",
        "build",
        "create",
        "design",
        "investigate",
        "analyze",
        "research",
        "system",
        "architecture",
        "workflow",
    )
    long_prompt_threshold: int = 160

    def should_plan(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return len(prompt) >= self.long_prompt_threshold or any(keyword in lowered for keyword in self.plan_keywords)
