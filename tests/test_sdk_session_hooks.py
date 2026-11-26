"""SessionStart and SessionEnd hooks fire around a session: once per query(), once per client."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import HOOK_EVENTS, AgentClient, AgentOptions, HookMatcher, ResultMessage, SystemMessage, query
from shipit_agent.stores.session import InMemorySessionStore


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.prompts.append(str(next(m.content for m in reversed(messages) if m.role == "user")))
        return LLMResponse(content="ok")


def _recorder(seen: list[dict[str, Any]], output: dict[str, Any] | None = None) -> Any:
    def hook(data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        seen.append(dict(data))
        return output or {}

    return hook


def _query(llm: _Model, tmp_path: Path, hooks: dict[str, Any], **options: Any) -> list[Any]:
    async def go() -> list[Any]:
        opts = AgentOptions(llm=llm, tools=[], cwd=tmp_path, hooks=hooks, **options)
        return [m async for m in query(prompt="go", options=opts)]

    return asyncio.run(go())


def test_both_events_are_known() -> None:
    assert {"SessionStart", "SessionEnd"} <= set(HOOK_EVENTS)


def test_a_query_starts_and_ends_one_session(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    hook = HookMatcher(None, [_recorder(seen)])
    messages = _query(_Model(), tmp_path, {"SessionStart": [hook], "SessionEnd": [hook]})
    assert isinstance(messages[-1], ResultMessage) and not messages[-1].is_error
    assert [d["hook_event_name"] for d in seen] == ["SessionStart", "SessionEnd"]
    assert seen[0]["source"] == "startup" and seen[1]["reason"] == "other"
    assert seen[0]["cwd"] == str(tmp_path.resolve()) and "session_id" in seen[0]


def test_resuming_reports_resume_and_a_matcher_filters_on_the_source(tmp_path: Path) -> None:
    store = InMemorySessionStore()
    fresh: list[dict[str, Any]] = []
    resumed: list[dict[str, Any]] = []
    hooks = {"SessionStart": [HookMatcher("startup", [_recorder(fresh)]), HookMatcher("resume", [_recorder(resumed)])]}
    _query(_Model(), tmp_path, hooks, session_store=store, session_id="s1")
    assert (len(fresh), len(resumed)) == (1, 0)
    _query(_Model(), tmp_path, hooks, session_store=store, resume="s1")
    assert (len(fresh), len(resumed)) == (1, 1) and resumed[0]["source"] == "resume"


def test_session_start_context_reaches_the_first_prompt(tmp_path: Path) -> None:
    llm = _Model()
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Today is Friday."}}
    _query(llm, tmp_path, {"SessionStart": [HookMatcher(None, [_recorder([], output)])]})
    assert "go" in llm.prompts[0] and "Today is Friday." in llm.prompts[0]


def test_async_hooks_work_and_a_failing_hook_does_not_end_the_run(tmp_path: Path) -> None:
    seen: list[str] = []

    async def slow(data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        await asyncio.sleep(0)
        seen.append(data["hook_event_name"])
        return {}

    def broken(*_: Any) -> dict[str, Any]:
        raise RuntimeError("hook bug")

    hooks = {"SessionStart": [HookMatcher(None, [broken, slow])], "SessionEnd": [HookMatcher(None, [slow, broken])]}
    messages = _query(_Model(), tmp_path, hooks)
    assert seen == ["SessionStart", "SessionEnd"] and not messages[-1].is_error


def test_hook_events_are_reported_when_asked_for(tmp_path: Path) -> None:
    messages = _query(_Model(), tmp_path, {"SessionStart": [HookMatcher(None, [_recorder([])])]}, include_hook_events=True)
    kinds = [(m.subtype, m.data.get("hook_event")) for m in messages if isinstance(m, SystemMessage)]
    assert ("hook_started", "SessionStart") in kinds and ("hook_response", "SessionStart") in kinds


def test_a_client_session_starts_once_and_ends_on_disconnect(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    llm = _Model()
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "House rules apply."}}
    hooks = {"SessionStart": [HookMatcher(None, [_recorder(seen, output)])], "SessionEnd": [HookMatcher(None, [_recorder(seen)])]}

    async def go() -> None:
        async with AgentClient(AgentOptions(llm=llm, tools=[], cwd=tmp_path, hooks=hooks)) as client:
            for prompt in ("one", "two"):
                await client.query(prompt)
                async for _ in client.receive_response():
                    pass
            assert [d["hook_event_name"] for d in seen] == ["SessionStart"]

    asyncio.run(go())
    assert [d["hook_event_name"] for d in seen] == ["SessionStart", "SessionEnd"]
    assert "House rules apply." in llm.prompts[0] and "House rules apply." not in llm.prompts[1]


def test_no_session_hooks_means_nothing_changes(tmp_path: Path) -> None:
    llm = _Model()
    messages = _query(llm, tmp_path, {})
    assert llm.prompts == ["go"] and not messages[-1].is_error


def test_an_unknown_event_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SessionBegin"):
        _query(_Model(), tmp_path, {"SessionBegin": [HookMatcher()]})
