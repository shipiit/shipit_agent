from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import JIRA_PROMPT


class JiraTool(HTTPConnectorToolBase):
    provider = "jira"

    def __init__(self, *, credential_key: str = "jira", credential_store=None, name: str = "jira", description: str = "Search Jira issues and create Jira issues.", prompt: str | None = None) -> None:
        super().__init__(credential_key=credential_key, credential_store=credential_store)
        self.name = name
        self.description = description
        self.prompt = prompt or JIRA_PROMPT
        self.prompt_instructions = "Use this for Jira search, ticket lookup, issue creation, transitions, comments, and assignee updates."

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["search_issues", "create_issue", "get_issue", "list_transitions", "transition_issue", "add_comment", "assign_issue"], "default": "search_issues"}, "jql": {"type": "string"}, "project_key": {"type": "string"}, "summary": {"type": "string"}, "description_text": {"type": "string"}, "issue_type": {"type": "string", "default": "Task"}, "issue_key": {"type": "string", "description": "Jira issue key such as PROJ-123"}, "transition_id": {"type": "string"}, "comment_body": {"type": "string"}, "account_id": {"type": "string", "description": "Jira account ID for assignment"}, "limit": {"type": "integer", "default": 10}}, "required": ["action"]}}}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_issues")).strip().lower()
        if action == "search_issues":
            data = self._request_json(record=record, method="POST", path="/rest/api/3/search", body={"jql": str(kwargs.get("jql", "")), "maxResults": int(kwargs.get("limit", 10)), "fields": ["summary", "status", "assignee"]})
            issues = data.get("issues", [])
            return ToolOutput(text="\n".join(f"{issue.get('key', '?')}: {issue.get('fields', {}).get('summary', '')} [{issue.get('fields', {}).get('status', {}).get('name', '')}]" for issue in issues) if issues else "No Jira issues found.", metadata={"provider": self.provider, "connected": True, "action": action, "items": issues, "count": len(issues)})
        if action == "create_issue":
            body = {"fields": {"project": {"key": str(kwargs.get("project_key", ""))}, "summary": str(kwargs.get("summary", "")), "description": str(kwargs.get("description_text", "")), "issuetype": {"name": str(kwargs.get("issue_type", "Task"))}}}
            data = self._request_json(record=record, method="POST", path="/rest/api/3/issue", body=body)
            return ToolOutput(text=f"Jira issue created: {data.get('key', '?')}", metadata={"provider": self.provider, "connected": True, "action": action, "issue": data})
        if action == "get_issue":
            issue_key = str(kwargs.get("issue_key", "")).strip()
            if not issue_key:
                return ToolOutput(text="issue_key is required for get_issue.", metadata={"provider": self.provider, "action": action})
            data = self._request_json(record=record, method="GET", path=f"/rest/api/3/issue/{issue_key}", query={"fields": "summary,status,assignee,description"})
            fields = data.get("fields", {})
            return ToolOutput(
                text=(
                    f"{data.get('key', issue_key)}: {fields.get('summary', '')}\n"
                    f"Status: {fields.get('status', {}).get('name', '?')}\n"
                    f"Assignee: {fields.get('assignee', {}).get('displayName', 'Unassigned')}"
                ),
                metadata={"provider": self.provider, "connected": True, "action": action, "issue": data},
            )
        if action == "list_transitions":
            issue_key = str(kwargs.get("issue_key", "")).strip()
            if not issue_key:
                return ToolOutput(text="issue_key is required for list_transitions.", metadata={"provider": self.provider, "action": action})
            data = self._request_json(record=record, method="GET", path=f"/rest/api/3/issue/{issue_key}/transitions")
            transitions = data.get("transitions", [])
            return ToolOutput(text="\n".join(f"{item.get('id', '?')}: {item.get('name', '?')}" for item in transitions) if transitions else f"No Jira transitions found for {issue_key}.", metadata={"provider": self.provider, "connected": True, "action": action, "items": transitions, "count": len(transitions)})
        if action == "transition_issue":
            issue_key = str(kwargs.get("issue_key", "")).strip()
            transition_id = str(kwargs.get("transition_id", "")).strip()
            if not issue_key or not transition_id:
                return ToolOutput(text="issue_key and transition_id are required for transition_issue.", metadata={"provider": self.provider, "action": action})
            data = self._request_json(record=record, method="POST", path=f"/rest/api/3/issue/{issue_key}/transitions", body={"transition": {"id": transition_id}})
            return ToolOutput(text=f"Jira issue transitioned: {issue_key} -> {transition_id}", metadata={"provider": self.provider, "connected": True, "action": action, "result": data})
        if action == "add_comment":
            issue_key = str(kwargs.get("issue_key", "")).strip()
            comment_body = str(kwargs.get("comment_body", "")).strip()
            if not issue_key or not comment_body:
                return ToolOutput(text="issue_key and comment_body are required for add_comment.", metadata={"provider": self.provider, "action": action})
            body = {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment_body}]}]}}
            data = self._request_json(record=record, method="POST", path=f"/rest/api/3/issue/{issue_key}/comment", body=body)
            return ToolOutput(text=f"Comment added to Jira issue {issue_key}.", metadata={"provider": self.provider, "connected": True, "action": action, "comment": data})
        if action == "assign_issue":
            issue_key = str(kwargs.get("issue_key", "")).strip()
            account_id = str(kwargs.get("account_id", "")).strip()
            if not issue_key or not account_id:
                return ToolOutput(text="issue_key and account_id are required for assign_issue.", metadata={"provider": self.provider, "action": action})
            data = self._request_json(record=record, method="PUT", path=f"/rest/api/3/issue/{issue_key}/assignee", body={"accountId": account_id})
            return ToolOutput(text=f"Jira issue assigned: {issue_key} -> {account_id}", metadata={"provider": self.provider, "connected": True, "action": action, "result": data})
        raise ValueError(f"Unsupported Jira action: {action}")
