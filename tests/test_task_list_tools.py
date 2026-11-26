"""``task_create``, ``task_update``, ``task_get`` and ``task_list``: the SDK's TaskCreate/Update/Get/List."""

from __future__ import annotations

import json
from typing import Any

import pytest

from shipit_agent.safety.permission_rules import sdk_tool_name
from shipit_agent.sdk.options import DEFAULT_TOOLS
from shipit_agent.tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool
from shipit_agent.tools.base import ToolContext


def _call(tool: Any, context: ToolContext, **arguments: Any) -> tuple[Any, bool]:
    out = tool.run(context, **arguments)
    return json.loads(out.text), bool(out.metadata.get("is_error"))


def _create(context: ToolContext, subject: str, **extra: Any) -> str:
    body, failed = _call(TaskCreateTool(), context, subject=subject, description=f"Do {subject}.", **extra)
    assert not failed
    return body["task"]["id"]


def test_create_list_and_get() -> None:
    context = ToolContext(prompt="")
    first = _create(context, "Write tests")
    second = _create(context, "Fix bug", activeForm="Fixing the bug")
    assert (first, second) == ("1", "2")
    listed, _ = _call(TaskListTool(), context)
    assert listed == {"tasks": [
        {"id": "1", "subject": "Write tests", "status": "pending", "owner": None, "blockedBy": []},
        {"id": "2", "subject": "Fix bug", "status": "pending", "owner": None, "blockedBy": []},
    ]}
    got, _ = _call(TaskGetTool(), context, taskId="2")
    assert got == {"task": {"id": "2", "subject": "Fix bug", "description": "Do Fix bug.", "status": "pending",
                            "blocks": [], "blockedBy": []}}
    assert _call(TaskGetTool(), context, taskId="9")[0] == {"task": None}


def test_update_reports_what_changed_and_links_both_sides_of_a_block() -> None:
    context = ToolContext(prompt="")
    a, b = _create(context, "A"), _create(context, "B")
    body, failed = _call(TaskUpdateTool(), context, taskId=a, status="in_progress", owner="me", addBlocks=[b])
    assert not failed
    assert body == {"success": True, "taskId": a, "updatedFields": ["status", "owner", "blocks"], "error": None,
                    "statusChange": {"from": "pending", "to": "in_progress"}}
    assert _call(TaskGetTool(), context, taskId=b)[0]["task"]["blockedBy"] == [a]
    assert _call(TaskGetTool(), context, taskId=a)[0]["task"]["blocks"] == [b]
    same, _ = _call(TaskUpdateTool(), context, taskId=a, status="in_progress")
    assert same["updatedFields"] == [] and same["statusChange"] is None


def test_deleting_a_task_removes_it_and_its_links() -> None:
    context = ToolContext(prompt="")
    a, b = _create(context, "A"), _create(context, "B")
    _call(TaskUpdateTool(), context, taskId=b, addBlockedBy=[a])
    body, failed = _call(TaskUpdateTool(), context, taskId=a, status="deleted")
    assert not failed and body["statusChange"] == {"from": "pending", "to": "deleted"}
    assert [t["id"] for t in _call(TaskListTool(), context)[0]["tasks"]] == [b]
    assert _call(TaskGetTool(), context, taskId=b)[0]["task"]["blockedBy"] == []
    assert _create(context, "C") == "3"  # ids are never reused


@pytest.mark.parametrize(
    ("arguments", "words"),
    [
        ({"taskId": "9", "status": "completed"}, "no task"),
        ({"taskId": "1", "status": "done"}, "status"),
        ({"taskId": "1", "addBlocks": ["1"]}, "itself"),
        ({"taskId": "1", "addBlockedBy": ["7"]}, "no task"),
        ({"taskId": "1", "addBlocks": "2"}, "list"),
        ({}, "taskId"),
    ],
)
def test_bad_updates_are_errors_and_change_nothing(arguments: dict[str, Any], words: str) -> None:
    context = ToolContext(prompt="")
    _create(context, "A")
    _create(context, "B")
    before = _call(TaskListTool(), context)[0]
    body, failed = _call(TaskUpdateTool(), context, **arguments)
    assert failed and body["success"] is False and words in body["error"]
    assert _call(TaskListTool(), context)[0] == before


@pytest.mark.parametrize("arguments", [{"subject": "", "description": "x"}, {"subject": "x"}, {"description": "x"}])
def test_create_needs_a_subject_and_a_description(arguments: dict[str, Any]) -> None:
    context = ToolContext(prompt="")
    out = TaskCreateTool().run(context, **arguments)
    assert out.metadata["is_error"] is True and "subject" in out.text
    assert "task_list" not in context.state  # nothing was created


def test_metadata_is_kept_and_merged() -> None:
    context = ToolContext(prompt="")
    task = _create(context, "A", metadata={"area": "api"})
    _call(TaskUpdateTool(), context, taskId=task, metadata={"pr": 7})
    assert context.state["task_list"]["tasks"][task]["metadata"] == {"area": "api", "pr": 7}


def test_they_are_opt_in_and_answer_to_the_sdk_names() -> None:
    names = {"TaskCreate": "task_create", "TaskUpdate": "task_update", "TaskGet": "task_get", "TaskList": "task_list"}
    for sdk, shipit in names.items():
        assert sdk_tool_name(sdk) == shipit and shipit not in DEFAULT_TOOLS
    assert TaskGetTool().read_only and TaskListTool().read_only
    assert not TaskCreateTool().read_only and not TaskUpdateTool().read_only
