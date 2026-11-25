"""A task list the model keeps while it works, with owners and dependencies.

Unlike ``todo``, which replaces the whole checklist on each call, these tools
change one task at a time, and a task can block others. The list lives in the
run's shared tool state; every answer is the SDK's JSON shape.
"""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

STATE_KEY = "task_list"
_STATUSES = ("pending", "in_progress", "completed", "deleted")


def _store(context: ToolContext) -> dict[str, Any]:
    return context.state.setdefault(STATE_KEY, {"next_id": 1, "tasks": {}})


def _answer(body: dict[str, Any], *, failed: bool = False) -> ToolOutput:
    text = json.dumps(body)
    return ToolOutput.error(text) if failed else ToolOutput(text=text)


def _function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


_ID = {"type": "string", "description": "The task's id"}
_IDS = {"type": "array", "items": {"type": "string"}}


class TaskCreateTool:
    name = "task_create"
    description = "Add a task to the run's task list."
    prompt_instructions = "Break multi-step work into tasks, then mark each in_progress and completed as you go."
    read_only = False

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description, {
            "subject": {"type": "string", "description": "A short title"},
            "description": {"type": "string", "description": "What the task involves"},
            "activeForm": {"type": "string", "description": "A present-tense label shown while it runs"},
            "metadata": {"type": "object", "description": "Any extra details to keep"},
        }, ["subject", "description"])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        subject = str(kwargs.get("subject") or "").strip()
        description = str(kwargs.get("description") or "").strip()
        if not subject or not description:
            return ToolOutput.error("Pass a `subject` and a `description` for the task.")
        store = _store(context)
        task_id = str(store["next_id"])
        store["next_id"] += 1
        store["tasks"][task_id] = {
            "id": task_id, "subject": subject, "description": description, "status": "pending",
            "activeForm": kwargs.get("activeForm"), "owner": None, "blocks": [], "blockedBy": [],
            "metadata": dict(kwargs.get("metadata") or {}),
        }
        return _answer({"task": {"id": task_id, "subject": subject}})


class TaskUpdateTool:
    name = "task_update"
    description = "Change one task: its status, text, owner or the tasks it blocks."
    prompt_instructions = "Set status to in_progress when you start a task, completed when done, deleted to drop it."
    read_only = False

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description, {
            "taskId": _ID,
            "status": {"type": "string", "enum": list(_STATUSES)},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "activeForm": {"type": "string"},
            "addBlocks": {**_IDS, "description": "Tasks this one now blocks"},
            "addBlockedBy": {**_IDS, "description": "Tasks that now block this one"},
            "owner": {"type": "string"},
            "metadata": {"type": "object"},
        }, ["taskId"])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        task_id = str(kwargs.get("taskId") or "").strip()
        tasks = _store(context)["tasks"]

        def refuse(error: str) -> ToolOutput:
            body = {"success": False, "taskId": task_id, "updatedFields": [], "error": error, "statusChange": None}
            return _answer(body, failed=True)

        if not task_id:
            return refuse("Pass `taskId`: the id of the task to change.")
        task = tasks.get(task_id)
        if task is None:
            return refuse(f"There is no task {task_id!r}.")
        status = kwargs.get("status")
        if status is not None and status not in _STATUSES:
            return refuse(f"status must be one of {', '.join(_STATUSES)}.")
        links: dict[str, list[str]] = {}
        for key in ("addBlocks", "addBlockedBy"):
            value = kwargs.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                return refuse(f"{key} must be a list of task ids.")
            ids = [str(other) for other in value]
            if task_id in ids:
                return refuse("A task cannot block itself.")
            unknown = [other for other in ids if other not in tasks]
            if unknown:
                return refuse(f"There is no task {', '.join(unknown)}.")
            links[key] = ids
        return _answer(_apply(tasks, task, status, links, kwargs))


def _apply(tasks: dict[str, Any], task: dict[str, Any], status: Any, links: dict[str, list[str]],
           kwargs: dict[str, Any]) -> dict[str, Any]:
    changed: list[str] = []
    change = None
    if status is not None and status != task["status"]:
        change = {"from": task["status"], "to": status}
        changed.append("status")
    for field in ("subject", "description", "activeForm", "owner"):
        if kwargs.get(field) is not None and kwargs[field] != task.get(field):
            task[field] = kwargs[field]
            changed.append(field)
    for key, mine, theirs in (("addBlocks", "blocks", "blockedBy"), ("addBlockedBy", "blockedBy", "blocks")):
        new = [other for other in links.get(key, []) if other not in task[mine]]
        for other in new:
            task[mine].append(other)
            tasks[other][theirs].append(task["id"])
        if new:
            changed.append(mine)
    if kwargs.get("metadata"):
        task["metadata"].update(dict(kwargs["metadata"]))
        changed.append("metadata")
    if status == "deleted":
        tasks.pop(task["id"])
        for other in tasks.values():
            for key in ("blocks", "blockedBy"):
                other[key] = [x for x in other[key] if x != task["id"]]
    elif status is not None:
        task["status"] = status
    return {"success": True, "taskId": task["id"], "updatedFields": changed, "error": None, "statusChange": change}


class TaskGetTool:
    name = "task_get"
    description = "Read one task in full."
    prompt_instructions = "Read a task before working on it to see what it blocks and is blocked by."
    read_only = True

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description, {"taskId": _ID}, ["taskId"])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        task = _store(context)["tasks"].get(str(kwargs.get("taskId") or "").strip())
        if task is None:
            return _answer({"task": None})
        keys = ("id", "subject", "description", "status", "blocks", "blockedBy")
        return _answer({"task": {key: task[key] for key in keys}})


class TaskListTool:
    name = "task_list"
    description = "List every task with its status, owner and blockers."
    prompt_instructions = "Check the list to pick the next unblocked task."
    read_only = True

    def schema(self) -> dict[str, Any]:
        return _function(self.name, self.description, {}, [])

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        tasks = _store(context)["tasks"].values()
        keys = ("id", "subject", "status", "owner", "blockedBy")
        return _answer({"tasks": [{key: task[key] for key in keys} for task in tasks]})
