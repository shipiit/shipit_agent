from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(slots=True)
class RetryPolicy:
    max_llm_retries: int = 2
    max_tool_retries: int = 1
    retry_on_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: (ConnectionError, TimeoutError, OSError)
    )
    #: Exponential backoff between LLM retries. A 429 retried with zero
    #: delay burns every attempt in microseconds against the same closed
    #: window; the delay is what turns "retries" into "recovery". Set 0
    #: to disable (tests that script failures shouldn't have to wait).
    llm_retry_base_delay: float = 0.5
    llm_retry_max_delay: float = 30.0
    #: Add up to +25% random jitter so parallel agents don't retry in
    #: lockstep against the same rate limit.
    llm_retry_jitter: bool = True
    #: Per-request LLM timeout in seconds, forwarded to adapters whose
    #: ``complete()`` accepts a ``timeout`` kwarg. ``None`` keeps each
    #: SDK's own default. A hung connection without a timeout hangs the
    #: whole run — ``cancel()`` only takes effect between steps.
    request_timeout: float | None = None

    def llm_retry_delay(self, attempt: int) -> float:
        """Seconds to wait before retry *attempt* (1-based)."""
        if self.llm_retry_base_delay <= 0:
            return 0.0
        delay = min(
            self.llm_retry_base_delay * (2 ** (attempt - 1)),
            self.llm_retry_max_delay,
        )
        if self.llm_retry_jitter:
            delay *= 1.0 + random.random() * 0.25
        return delay


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
        return len(prompt) >= self.long_prompt_threshold or any(
            keyword in lowered for keyword in self.plan_keywords
        )
