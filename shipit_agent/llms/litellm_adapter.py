from __future__ import annotations

import json
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall


def _serialize_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        **({"name": message.name} if message.name else {}),
    }
    tool_calls = message.metadata.get("tool_calls", [])
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.get("id", f"call_{index}"),
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": json.dumps(item.get("arguments", {}), sort_keys=True),
                },
            }
            for index, item in enumerate(tool_calls, start=1)
        ]
    tool_call_id = message.metadata.get("tool_call_id")
    if message.role == "tool" and tool_call_id:
        payload["tool_call_id"] = tool_call_id
    return payload


class LiteLLMChatLLM:
    def __init__(self, model: str, **completion_kwargs: Any) -> None:
        self.model = model
        self.completion_kwargs = completion_kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError("Install `litellm` to use LiteLLMChatLLM.") from exc

        payload_messages = [_serialize_message(m) for m in messages]
        response = completion(
            model=self.model,
            messages=payload_messages,
            tools=tools or None,
            **self.completion_kwargs,
        )
        message = response.choices[0].message
        tool_calls = []
        for call in getattr(message, "tool_calls", []) or []:
            arguments = call.function.arguments or "{}"
            tool_calls.append(
                ToolCall(
                    name=call.function.name,
                    arguments=json.loads(arguments) if isinstance(arguments, str) else arguments,
                )
            )
        return LLMResponse(
            content=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
            metadata={"model": self.model, "provider": "litellm"},
        )


class BedrockChatLLM(LiteLLMChatLLM):
    def __init__(self, model: str = "bedrock/openai.gpt-oss-120b-1:0", **completion_kwargs: Any) -> None:
        # Bedrock requires strict tool_use/tool_result id pairing. The shipit_agent
        # Message model doesn't carry tool-call IDs, so we let litellm patch the
        # request on our behalf (inserts dummy assistant turns + filler tool_results
        # where needed). Without this, Bedrock rejects multi-step tool runs with
        # "Expected toolResult blocks ... for Ids: <uuid>".
        completion_kwargs.setdefault("modify_params", True)
        super().__init__(model=model, **completion_kwargs)
        # Also set the global flag as a belt-and-braces measure — some litellm
        # code paths consult litellm.modify_params directly rather than kwargs.
        try:
            import litellm  # type: ignore
            litellm.modify_params = True
        except Exception:
            pass


class GeminiChatLLM(LiteLLMChatLLM):
    def __init__(self, model: str = "gemini/gemini-1.5-pro", **completion_kwargs: Any) -> None:
        super().__init__(model=model, **completion_kwargs)


class GroqChatLLM(LiteLLMChatLLM):
    def __init__(self, model: str = "groq/llama-3.3-70b-versatile", **completion_kwargs: Any) -> None:
        super().__init__(model=model, **completion_kwargs)


class TogetherChatLLM(LiteLLMChatLLM):
    def __init__(self, model: str = "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo", **completion_kwargs: Any) -> None:
        super().__init__(model=model, **completion_kwargs)


class OllamaChatLLM(LiteLLMChatLLM):
    def __init__(self, model: str = "ollama/llama3.1", **completion_kwargs: Any) -> None:
        super().__init__(model=model, **completion_kwargs)
