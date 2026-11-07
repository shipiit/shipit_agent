"""Background tasks, as in the Claude Agent SDK: started, noticed, stopped, and
told to the model when they finish.

The bash jobs here are real processes running harmless commands (sleep, echo).
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Callable

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.core.tasks import TaskInfo, background_tasks, notification_text
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, SystemMessage, query
from shipit_agent.tools.bash.bash_tool import BashTool
from shipit_agent.tools.bash.jobs import BashJobTool
from shipit_agent.tools.sub_agent import SubAgentTool
from shipit_agent.tools.task_stop import TaskStopTool


def _wait(seconds: float = 0.0) -> str:
    """Wait a moment."""
    time.sleep(seconds)
    return "waited"


WAIT = FunctionTool.from_callable(_wait, name="wait")


class _Steps:
    """Each step is a function of the conversation so far, returning a response."""

    model = "claude-sonnet-5-5"

    def __init__(self, *steps: Callable[[list[str]], LLMResponse]) -> None:
        self.steps = list(steps)
        self.seen: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        texts = [str(m.content) for m in messages]
        self.seen.append(texts)
        return self.steps.pop(0)(texts) if self.steps else LLMResponse(content="done")


def _call(name: str, **arguments: Any) -> Callable[[list[str]], LLMResponse]:
    return lambda _texts: LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments)])


def _job_id(texts: list[str]) -> str:
    match = next(m for t in reversed(texts) if (m := re.search(r"as (job_\S+?) \(pid", t)))
    return match.group(1)


def _bash_agent(tmp_path: Path, llm: _Steps) -> Agent:
    bash = BashTool(root_dir=tmp_path)
    return Agent(llm=llm, tools=[bash, BashJobTool(bash), TaskStopTool(), WAIT], project_root=tmp_path,
                 permission_mode="bypassPermissions")


def test_a_finished_bash_job_is_told_to_the_model(tmp_path: Path) -> None:
    llm = _Steps(_call("bash", command="sleep 0.5 && echo built", background=True),
                 _call("wait", seconds=1.0))
    result = _bash_agent(tmp_path, llm).run("build in the background")
    told = [t for t in llm.seen[-1] if t.startswith("<task-notification>")]
    assert len(told) == 1 and "completed" in told[0] and "bg_" in told[0]
    kinds = [e.type for e in result.events]
    assert "task_started" in kinds and "task_notification" in kinds
    note = next(e for e in result.events if e.type == "task_notification")
    assert note.payload["task_type"] == "local_bash" and note.payload["status"] == "completed"


def test_task_stop_stops_a_running_job_and_it_is_not_reported_as_done(tmp_path: Path) -> None:
    llm = _Steps(_call("bash", command="sleep 30", background=True),
                 lambda texts: LLMResponse(content="", tool_calls=[ToolCall(name="task_stop",
                                                                             arguments={"task_id": _job_id(texts)})]))
    agent = _bash_agent(tmp_path, llm)
    result = agent.run("start then stop")
    stopped = next(r for r in result.tool_results if r.name == "task_stop")
    assert stopped.output.startswith("Stopped job_")
    bash = agent.tools[0]
    assert all(task.status == "stopped" for task in bash.list_background_tasks())
    assert not any(t.startswith("<task-notification>") for t in llm.seen[-1])


def test_stopping_an_unknown_task_lists_what_is_running(tmp_path: Path) -> None:
    llm = _Steps(_call("task_stop", task_id="job_9"))
    result = _bash_agent(tmp_path, llm).run("stop")
    assert "No background task 'job_9'" in result.tool_results[0].output


def test_a_finished_background_sub_agent_is_told_with_a_summary(tmp_path: Path) -> None:
    class _Child:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="Found three flaky tests in test_api.py.")

    llm = _Steps(_call("sub_agent", task="find flaky tests", background=True), _call("wait", seconds=0.5))
    sub_agent = SubAgentTool(_Child())
    result = Agent(llm=llm, tools=[sub_agent, TaskStopTool(), WAIT], project_root=tmp_path).run("delegate")
    told = next(t for t in llm.seen[-1] if t.startswith("<task-notification>"))
    assert "completed" in told and "Found three flaky tests" in told and "collect" in told
    assert any(e.type == "task_notification" and e.payload["task_type"] == "local_agent" for e in result.events)


def test_each_change_is_reported_once(tmp_path: Path) -> None:
    llm = _Steps(_call("bash", command="echo quick", background=True), _call("wait", seconds=0.3),
                 _call("wait"), _call("wait"))
    result = _bash_agent(tmp_path, llm).run("go")
    assert [e.type for e in result.events].count("task_notification") == 1
    assert [e.type for e in result.events].count("task_started") == 1


def test_tools_behind_a_wrapper_are_seen() -> None:
    class _Owner:
        def list_background_tasks(self) -> list[TaskInfo]:
            return [TaskInfo("t1", "local_bash", "make", "running")]

    class _Wrapper:
        def __init__(self, tool: Any) -> None:
            self._tool = tool

        def __getattr__(self, item: str) -> Any:
            return getattr(object.__getattribute__(self, "_tool"), item)

    assert [t.task_id for t in background_tasks([object(), _Wrapper(_Owner())])] == ["t1"]


def test_the_notification_names_the_task_its_output_and_a_failure() -> None:
    text = notification_text(TaskInfo("job_1", "local_bash", "npm test", "failed", output_file="/tmp/log", exit_code=1))
    assert text.startswith("<task-notification>") and "job_1 (npm test) failed" in text
    assert "Exit code: 1" in text and "/tmp/log" in text


def test_the_sdk_stream_carries_task_messages(tmp_path: Path) -> None:
    llm = _Steps(_call("bash", command="echo quick", background=True), _call("wait", seconds=0.3))

    async def run() -> list[Any]:
        bash = BashTool(root_dir=tmp_path)
        options = AgentOptions(llm=llm, cwd=tmp_path, tools=[bash, TaskStopTool(), WAIT],
                               permission_mode="bypassPermissions")
        return [m async for m in query(prompt="go", options=options)]

    subtypes = [m.subtype for m in asyncio.run(run()) if isinstance(m, SystemMessage)]
    assert "task_started" in subtypes and "task_notification" in subtypes
