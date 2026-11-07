"""AskUserQuestion through can_use_tool, and streaming input, as in the Claude Agent SDK."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentClient,
    AgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    UserMessage,
    build_agent,
    query,
)

QUESTIONS = [
    {"question": "Which database?", "header": "Database", "multiSelect": False,
     "options": [{"label": "Postgres", "description": "Relational"}, {"label": "Mongo", "description": "Documents"}]},
    {"question": "Which targets?", "header": "Targets", "multiSelect": True,
     "options": [{"label": "iOS", "description": "Apple"}, {"label": "Android", "description": "Google"}]},
]


class _Asks:
    model = "claude-sonnet-5-5"

    def __init__(self, arguments: dict[str, Any] | None = None) -> None:
        self.arguments = {"questions": QUESTIONS} if arguments is None else arguments
        self.asked = False
        self.users: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.users.append([str(m.content) for m in messages if m.role == "user"])
        if not self.asked:
            self.asked = True
            return LLMResponse(content="", tool_calls=[ToolCall(name="ask_user", arguments=self.arguments, id="q1")])
        return LLMResponse(content="done")


def _answer_block(**options: Any) -> Any:
    async def run() -> list[Any]:
        return [m async for m in query(prompt="Pick a stack", options=AgentOptions(**options))]

    return next(m for m in asyncio.run(run()) if isinstance(m, UserMessage)).content[0]


def test_questions_reach_can_use_tool_and_the_answers_reach_the_model() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def can_use_tool(name: str, input_data: dict[str, Any], context: Any) -> Any:
        seen.append((name, input_data))
        return PermissionResultAllow(updated_input={**input_data, "answers": {
            "Which database?": "Postgres", "Which targets?": ["iOS", "Android"]}})

    block = _answer_block(llm=_Asks(), tools=["AskUserQuestion"], can_use_tool=can_use_tool)
    assert seen == [("AskUserQuestion", {"questions": QUESTIONS})]
    assert "Which database? → Postgres" in block.content and "Which targets? → iOS, Android" in block.content


def test_a_free_reply_is_passed_on() -> None:
    block = _answer_block(llm=_Asks(), tools=["AskUserQuestion"],
                          can_use_tool=lambda *_: {"behavior": "allow", "updated_input": {"response": "you choose"}})
    assert block.content == "The user responded: you choose"


def test_a_declined_or_unanswerable_question_asks_the_model_to_assume() -> None:
    declined = _answer_block(llm=_Asks(), tools=["AskUserQuestion"],
                             can_use_tool=lambda *_: PermissionResultDeny(message="Not now"))
    assert declined.content.startswith("Not now.") and "assumption" in declined.content
    unanswered = _answer_block(llm=_Asks(), tools=["AskUserQuestion"])
    assert "No one can answer" in unanswered.content and not unanswered.is_error


def test_malformed_questions_are_an_error_the_model_can_fix() -> None:
    block = _answer_block(llm=_Asks({"questions": []}), tools=["AskUserQuestion"], can_use_tool=lambda *_: None)
    assert block.is_error and "questions" in block.content


def test_the_default_tools_ask_in_the_sdk_format() -> None:
    agent = build_agent(AgentOptions(llm=_Asks()))
    ask = next(tool for tool in agent.tools if tool.name == "ask_user")
    assert "questions" in ask.schema()["function"]["parameters"]["properties"]


# -- streaming input ---------------------------------------------------------------


class _Echo:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.users: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.users.append([str(m.content) for m in messages if m.role == "user"])
        return LLMResponse(content=f"reply {len(self.users)}")


async def _messages() -> AsyncIterator[dict[str, Any]]:
    yield {"type": "user", "message": {"role": "user", "content": "My name is Ada."}}
    yield {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "What is my name?"}]}}


def test_streaming_input_runs_each_message_as_a_turn_of_one_conversation() -> None:
    llm = _Echo()

    async def run() -> list[Any]:
        return [m async for m in query(prompt=_messages(), options=AgentOptions(llm=llm, tools=[]))]

    messages = asyncio.run(run())
    results = [m for m in messages if isinstance(m, ResultMessage)]
    assert [r.result for r in results] == ["reply 1", "reply 2"]
    assert any("My name is Ada." in text for text in llm.users[1])
    assert "What is my name?" in llm.users[1][-1]
    assert isinstance(messages[0], UserMessage) and not any(isinstance(m, SystemMessage) and m.subtype != "init"
                                                            for m in messages)


def test_the_client_takes_a_message_stream_too() -> None:
    llm = _Echo()

    async def run() -> list[Any]:
        async with AgentClient(AgentOptions(llm=llm, tools=[])) as client:
            await client.query(_messages())
            first = [m async for m in client.receive_response()]
            second = [m async for m in client.receive_response()]
            return [first[-1], second[-1]]

    assert [r.result for r in asyncio.run(run())] == ["reply 1", "reply 2"]
