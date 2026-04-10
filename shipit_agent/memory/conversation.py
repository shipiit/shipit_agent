from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shipit_agent.models import Message


@dataclass(slots=True)
class ConversationMemory:
    """Conversation memory with multiple strategies.

    Strategies:
    - ``buffer``: Keep all messages (no truncation)
    - ``window``: Keep the last ``window_size`` messages
    - ``summary``: Summarize old messages using an LLM
    - ``token``: Keep messages within ``max_tokens`` budget

    Example::

        memory = ConversationMemory(strategy="window", window_size=20)
        memory.add(Message(role="user", content="Hello"))
        messages = memory.get_messages()  # returns last 20
    """

    strategy: Literal["buffer", "window", "summary", "token"] = "buffer"
    window_size: int = 20
    max_tokens: int = 4000
    summary_llm: Any = None
    messages: list[Message] = field(default_factory=list)
    _summary: str = ""

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def add_many(self, messages: list[Message]) -> None:
        self.messages.extend(messages)

    def get_messages(self) -> list[Message]:
        if self.strategy == "buffer":
            return list(self.messages)
        elif self.strategy == "window":
            return list(self.messages[-self.window_size :])
        elif self.strategy == "token":
            return self._get_by_token_limit()
        elif self.strategy == "summary":
            return self._get_with_summary()
        return list(self.messages)

    def _get_by_token_limit(self) -> list[Message]:
        """Keep messages from the end within the token budget."""
        result: list[Message] = []
        total = 0
        for msg in reversed(self.messages):
            est_tokens = len(msg.content) // 4
            if total + est_tokens > self.max_tokens:
                break
            result.insert(0, msg)
            total += est_tokens
        return result

    def _get_with_summary(self) -> list[Message]:
        """Summarize older messages, keep recent ones."""
        if len(self.messages) <= self.window_size:
            return list(self.messages)

        old = self.messages[: -self.window_size]
        recent = self.messages[-self.window_size :]

        # Summarize old messages
        if self.summary_llm and old:
            old_text = "\n".join(f"{m.role}: {m.content[:200]}" for m in old)
            prompt = f"Summarize this conversation concisely:\n{old_text}"
            try:
                response = self.summary_llm.complete(
                    messages=[Message(role="user", content=prompt)],
                )
                self._summary = response.content
            except Exception:
                self._summary = f"[{len(old)} earlier messages]"
        else:
            self._summary = f"[{len(old)} earlier messages]"

        summary_msg = Message(
            role="system",
            content=f"Previous conversation summary: {self._summary}",
            metadata={"summary": True},
        )
        return [summary_msg] + recent

    def clear(self) -> None:
        self.messages.clear()
        self._summary = ""
