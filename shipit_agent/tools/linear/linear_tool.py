from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import LINEAR_PROMPT


class LinearTool(HTTPConnectorToolBase):
    provider = "linear"

    def __init__(
        self,
        *,
        credential_key: str = "linear",
        credential_store=None,
        name: str = "linear",
        description: str = "Search Linear issues and create Linear issues.",
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or LINEAR_PROMPT
        self.prompt_instructions = "Use this for issue tracking, team and project lookup, issue search, creation, and updates in Linear."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "search_issues",
                                "create_issue",
                                "get_issue",
                                "update_issue",
                                "list_teams",
                                "list_projects",
                            ],
                            "default": "search_issues",
                        },
                        "query": {"type": "string"},
                        "title": {"type": "string"},
                        "team_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "issue_id": {
                            "type": "string",
                            "description": "Linear issue ID for update_issue",
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Linear issue identifier such as ENG-123 for get_issue",
                        },
                        "description_text": {"type": "string"},
                        "state_id": {"type": "string"},
                        "assignee_id": {"type": "string"},
                        "priority": {"type": "integer"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["action"],
                },
            },
        }

    def _base_url(self, record):
        return "https://api.linear.app/graphql"

    def _request_json(self, *, record, method, path, query=None, body=None):
        return super()._request_json(record=record, method=method, path="", body=body)

    def _graphql(
        self, *, record, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        data = self._request_json(
            record=record,
            method="POST",
            path="",
            body={"query": query, "variables": variables},
        )
        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(
                f"Linear API error: {errors[0].get('message', 'unknown_error')}"
            )
        return data.get("data", {})

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_issues")).strip().lower()
        if action == "search_issues":
            data = self._graphql(
                record=record,
                query="query SearchIssues($term: String!, $first: Int!) { issues(first: $first, filter: { title: { containsIgnoreCase: $term } }) { nodes { id identifier title priority state { name } assignee { name } } } }",
                variables={
                    "term": str(kwargs.get("query", "")),
                    "first": int(kwargs.get("limit", 10)),
                },
            )
            items = data.get("issues", {}).get("nodes", [])
            return ToolOutput(
                text="\n".join(
                    f"{item.get('identifier', '?')}: {item.get('title', '')} [{item.get('state', {}).get('name', '')}]"
                    for item in items
                )
                if items
                else "No Linear issues found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": items,
                    "count": len(items),
                },
            )
        if action == "create_issue":
            data = self._graphql(
                record=record,
                query="mutation CreateIssue($teamId: String!, $title: String!, $description: String, $priority: Int, $assigneeId: String, $projectId: String) { issueCreate(input: { teamId: $teamId, title: $title, description: $description, priority: $priority, assigneeId: $assigneeId, projectId: $projectId }) { success issue { id identifier title } } }",
                variables={
                    "teamId": str(kwargs.get("team_id", "")),
                    "title": str(kwargs.get("title", "")),
                    "description": str(kwargs.get("description_text", "")),
                    "priority": kwargs.get("priority"),
                    "assigneeId": kwargs.get("assignee_id"),
                    "projectId": kwargs.get("project_id"),
                },
            )
            issue = data.get("issueCreate", {}).get("issue", {})
            return ToolOutput(
                text=f"Linear issue created: {issue.get('identifier', '?')} {issue.get('title', '')}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "issue": issue,
                },
            )
        if action == "get_issue":
            identifier = str(kwargs.get("identifier", "")).strip()
            if not identifier:
                return ToolOutput(
                    text="identifier is required for get_issue.",
                    metadata={"provider": self.provider, "action": action},
                )
            data = self._graphql(
                record=record,
                query="query GetIssue($identifier: String!) { issues(first: 1, filter: { identifier: { eq: $identifier } }) { nodes { id identifier title description priority state { id name } assignee { id name } project { id name } } } }",
                variables={"identifier": identifier},
            )
            items = data.get("issues", {}).get("nodes", [])
            issue = items[0] if items else {}
            text = (
                (
                    f"{issue.get('identifier', identifier)}: {issue.get('title', '')}\n"
                    f"State: {issue.get('state', {}).get('name', '?')}\n"
                    f"Priority: {issue.get('priority', '?')}\n"
                    f"Assignee: {issue.get('assignee', {}).get('name', 'Unassigned')}\n"
                    f"Project: {issue.get('project', {}).get('name', 'None')}"
                )
                if issue
                else f"No Linear issue found for {identifier}."
            )
            return ToolOutput(
                text=text,
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "issue": issue,
                },
            )
        if action == "update_issue":
            issue_id = str(kwargs.get("issue_id", "")).strip()
            if not issue_id:
                return ToolOutput(
                    text="issue_id is required for update_issue.",
                    metadata={"provider": self.provider, "action": action},
                )
            data = self._graphql(
                record=record,
                query="mutation UpdateIssue($id: String!, $title: String, $description: String, $stateId: String, $assigneeId: String, $priority: Int) { issueUpdate(id: $id, input: { title: $title, description: $description, stateId: $stateId, assigneeId: $assigneeId, priority: $priority }) { success issue { id identifier title } } }",
                variables={
                    "id": issue_id,
                    "title": kwargs.get("title"),
                    "description": kwargs.get("description_text"),
                    "stateId": kwargs.get("state_id"),
                    "assigneeId": kwargs.get("assignee_id"),
                    "priority": kwargs.get("priority"),
                },
            )
            issue = data.get("issueUpdate", {}).get("issue", {})
            return ToolOutput(
                text=f"Linear issue updated: {issue.get('identifier', issue_id)} {issue.get('title', '')}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "issue": issue,
                },
            )
        if action == "list_teams":
            data = self._graphql(
                record=record,
                query="query ListTeams { teams { nodes { id key name } } }",
                variables={},
            )
            items = data.get("teams", {}).get("nodes", [])
            return ToolOutput(
                text="\n".join(
                    f"{item.get('name', '?')} ({item.get('key', '?')})"
                    for item in items
                )
                if items
                else "No Linear teams found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": items,
                    "count": len(items),
                },
            )
        if action == "list_projects":
            data = self._graphql(
                record=record,
                query="query ListProjects($first: Int!) { projects(first: $first) { nodes { id name slug state color } } }",
                variables={"first": int(kwargs.get("limit", 10))},
            )
            items = data.get("projects", {}).get("nodes", [])
            query = str(kwargs.get("query", "")).strip().lower()
            if query:
                items = [
                    item
                    for item in items
                    if query in str(item.get("name", "")).lower()
                    or query in str(item.get("slug", "")).lower()
                ]
            return ToolOutput(
                text="\n".join(
                    f"{item.get('name', '?')} ({item.get('slug', '?')}) [{item.get('state', '?')}]"
                    for item in items
                )
                if items
                else "No Linear projects found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": items,
                    "count": len(items),
                },
            )
        raise ValueError(f"Unsupported Linear action: {action}")
