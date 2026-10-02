"""StepRouter — pick the model per step of a run, not per prompt.

Most steps inside one run are routine: read a tool result, choose the next
call. A small model does those well. Planning a turn, recovering from a failed
tool, and writing the answer the user reads are where a strong model earns its
price. Pass a ``StepRouter`` as ``llm=`` and each step goes to the right one.

Routine steps run on ``fast`` with their text buffered rather than streamed. If
the fast model calls tools, its brief narration is released and the step
stands. If it writes prose instead — it is answering — the step is re-run on
``strong``, streaming live, so the user never reads the small model's answer and
never sees text twice. Past ``escalate_after_chars`` the fast stream is cut
early, which caps the waste on adapters that stop when the text callback
returns ``False`` (the OpenAI-compatible and LiteLLM ones do). Elsewhere the
fast call finishes before escalating: still correct, but it costs more.

The escalated step's discarded call rides on ``metadata["discarded_usage"]``
(estimated when the provider never reported it) so budgets and cost stay
honest.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.llms.base import (
    accepts_explicit_kwarg,
    accepts_kwarg,
    accepts_text_delta_callback,
    accepts_tool_input_callback,
)

#: Set by the run loop on the user's real prompt. Runtime-injected user
#: messages (reminders, retry nudges) never carry it, so they cannot make a
#: routine step look like the start of a turn.
TURN_START = "turn_start"

#: Side calls that condense rather than decide — cheap-model work.
SUMMARY_PURPOSES = frozenset({"context_compaction", "agent_decision_summary"})

#: Steps the fast model runs; every other step runs on the strong model.
FAST_STEPS = frozenset({"digest", "summary"})


def _get(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _last(history: list[Any], flag: str) -> int | None:
    """Index of the newest message whose metadata sets *flag*."""
    return next((i for i in range(len(history) - 1, -1, -1)
                 if (_get(history[i], "metadata") or {}).get(flag)), None)


def classify_step(messages: Any, *, tools: Any, metadata: Any) -> str:
    """Name the step a request represents.

    ``summary`` / ``side`` — a side call, by its ``metadata.purpose``;
    ``answer`` — no tools offered, so the reply is the answer;
    ``plan`` — nothing has happened yet in the latest turn (also the safe
    fallback when no turn marker is present);
    ``recover`` — the last tool round contained a failure;
    ``digest`` — reading successful tool results to choose what is next.
    """
    purpose = (metadata or {}).get("purpose")
    if purpose in SUMMARY_PURPOSES:
        return "summary"
    if purpose:
        return "side"
    if not tools:
        return "answer"
    history = list(messages or [])
    start = _last(history, TURN_START)
    if start is None:
        # Compaction can fold the turn's opening prompt into a summary; the
        # summary then marks where the retained, mid-turn context begins.
        start = _last(history, "compacted")
    if start is None:
        return "plan"
    tail = history[start + 1 :]
    replied = [i for i, m in enumerate(tail) if _get(m, "role") == "assistant"]
    if not replied:
        return "plan"
    latest = tail[replied[-1] + 1 :]
    if any(_get(m, "role") == "tool" and (_get(m, "metadata") or {}).get("error") for m in latest):
        return "recover"
    return "digest"


@dataclass(slots=True)
class RouteReport:
    """What the router did across its lifetime."""

    steps: dict[str, int] = field(default_factory=dict)
    escalations: int = 0
    discarded_tokens: int = 0

    def record(self, step: str, discarded: dict[str, Any] | None) -> None:
        self.steps[step] = self.steps.get(step, 0) + 1
        if discarded is not None:
            self.escalations += 1
            self.discarded_tokens += int(discarded.get("prompt_tokens", 0)) + int(
                discarded.get("completion_tokens", 0))

    def to_dict(self) -> dict[str, Any]:
        return {"steps": dict(self.steps), "escalations": self.escalations,
                "discarded_tokens": self.discarded_tokens}


class _Buffer:
    """Holds a fast step's text; asks the stream to stop past ``limit``."""

    def __init__(self, limit: int) -> None:
        self.limit, self.chunks, self.size = limit, [], 0

    def feed(self, chunk: str) -> bool | None:
        if chunk:
            self.chunks.append(chunk)
            self.size += len(chunk)
        return False if self.size > self.limit else None

    def release(self, callback: Callable[[str], Any] | None) -> None:
        if callback is None:
            return
        for chunk in self.chunks:
            if callback(chunk) is False:
                return


def _call_kwargs(fn: Any, call: dict[str, Any], text_cb: Any, tool_cb: Any,
                 require: bool) -> dict[str, Any]:
    kwargs = {"messages": call["messages"]}
    kwargs.update({k: v for k, v in call.items() if k != "messages" and accepts_kwarg(fn, k)})
    if text_cb is not None and accepts_text_delta_callback(fn):
        kwargs["text_delta_callback"] = text_cb
    if tool_cb is not None and accepts_tool_input_callback(fn):
        kwargs["tool_input_callback"] = tool_cb
    if require and accepts_explicit_kwarg(fn, "require_tool_call"):
        kwargs["require_tool_call"] = True
    return kwargs


def _usage_of(response: Any, call: dict[str, Any], model: Any) -> dict[str, Any]:
    """The discarded call's usage, estimated when the provider never sent it."""
    usage = dict(getattr(response, "usage", None) or {})
    if usage.get("prompt_tokens") and usage.get("completion_tokens"):
        return usage
    from shipit_agent.compaction import count_messages, estimate_tokens

    prompt = count_messages(call["messages"], model) + estimate_tokens(
        call.get("system_prompt") or "") + estimate_tokens(json.dumps(call.get("tools") or []))
    completion = estimate_tokens(getattr(response, "content", "") or "")
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion, "estimated": True}


class StepRouter:
    """A drop-in LLM that sends each step to ``fast`` or ``strong``."""

    def __init__(self, *, fast: Any, strong: Any, escalate_after_chars: int = 600) -> None:
        if type(escalate_after_chars) is not int or escalate_after_chars < 1:
            raise ValueError("escalate_after_chars must be a positive integer")
        self.fast, self.strong = fast, strong
        self.escalate_after_chars = escalate_after_chars
        self.report = RouteReport()

    @property
    def model(self) -> Any:
        """The model with the tighter window, so compaction fits both."""
        from shipit_agent.compaction import get_model_limits

        fast, strong = getattr(self.fast, "model", None), getattr(self.strong, "model", None)
        if not fast or not strong:
            return strong or fast
        tighter = get_model_limits(fast).context_window < get_model_limits(strong).context_window
        return fast if tighter else strong

    def complete(self, *, messages: Any, tools: Any = None, system_prompt: Any = None,
                 metadata: Any = None, text_delta_callback: Any = None,
                 tool_input_callback: Any = None, require_tool_call: bool = False,
                 **kwargs: Any) -> Any:
        call = {"messages": list(messages), "tools": tools, "system_prompt": system_prompt,
                "metadata": metadata, **kwargs}

        def run(llm: Any, text_cb: Any) -> Any:
            fn = llm.complete
            return fn(**_call_kwargs(fn, call, text_cb, tool_input_callback, require_tool_call))

        step = classify_step(call["messages"], tools=tools, metadata=metadata)
        if step != "digest" or require_tool_call:
            llm = self.fast if step in FAST_STEPS else self.strong
            return self._done(step, llm, run(llm, text_delta_callback), call)
        buffer = _Buffer(self.escalate_after_chars)
        response = run(self.fast, buffer.feed)
        if getattr(response, "tool_calls", None):
            buffer.release(text_delta_callback)
            return self._done(step, self.fast, response, call)
        final = run(self.strong, text_delta_callback)
        return self._done("escalated", self.strong, final, call, discarded=response)

    async def acomplete(self, *, messages: Any, tools: Any = None, system_prompt: Any = None,
                        metadata: Any = None, text_delta_callback: Any = None,
                        tool_input_callback: Any = None, require_tool_call: bool = False,
                        **kwargs: Any) -> Any:
        call = {"messages": list(messages), "tools": tools, "system_prompt": system_prompt,
                "metadata": metadata, **kwargs}

        async def run(llm: Any, text_cb: Any) -> Any:
            native = getattr(llm, "acomplete", None)
            fn = native if callable(native) else llm.complete
            args = _call_kwargs(fn, call, text_cb, tool_input_callback, require_tool_call)
            if not callable(native):
                return await asyncio.to_thread(fn, **args)
            result = fn(**args)
            return await result if inspect.isawaitable(result) else result

        step = classify_step(call["messages"], tools=tools, metadata=metadata)
        if step != "digest" or require_tool_call:
            llm = self.fast if step in FAST_STEPS else self.strong
            return self._done(step, llm, await run(llm, text_delta_callback), call)
        buffer = _Buffer(self.escalate_after_chars)
        response = await run(self.fast, buffer.feed)
        if getattr(response, "tool_calls", None):
            buffer.release(text_delta_callback)
            return self._done(step, self.fast, response, call)
        final = await run(self.strong, text_delta_callback)
        return self._done("escalated", self.strong, final, call, discarded=response)

    def _done(self, step: str, llm: Any, response: Any, call: dict[str, Any],
              discarded: Any = None) -> Any:
        spent = None if discarded is None else _usage_of(
            discarded, call, getattr(self.fast, "model", None))
        if spent is not None:
            spent["model"] = getattr(self.fast, "model", None)
        meta = getattr(response, "metadata", None)
        if isinstance(meta, dict):
            meta["route"] = {"step": step, "model": getattr(llm, "model", None)}
            if spent is not None:
                meta["discarded_usage"] = spent
        self.report.record(step, spent)
        return response
