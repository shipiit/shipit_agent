from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import CONFLUENCE_PROMPT


class ConfluenceTool(HTTPConnectorToolBase):
    provider = "confluence"

    def __init__(
        self,
        *,
        credential_key: str = "confluence",
        credential_store=None,
        name: str = "confluence",
        description: str = "Search and create Confluence pages.",
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or CONFLUENCE_PROMPT
        self.prompt_instructions = (
            "Use this for Confluence documentation search and page creation."
        )

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
                            "enum": ["search_pages", "create_page"],
                            "default": "search_pages",
                        },
                        "query": {"type": "string"},
                        "space_key": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_pages"))
        if action == "search_pages":
            data = self._request_json(
                record=record,
                method="GET",
                path="/wiki/rest/api/search",
                query={"cql": f'text ~ "{str(kwargs.get("query", ""))}"'},
            )
            items = data.get("results", [])
            return ToolOutput(
                text="\n".join(item.get("title", "") for item in items)
                if items
                else "No Confluence pages found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": items,
                    "count": len(items),
                },
            )
        if action == "create_page":
            body = {
                "type": "page",
                "title": str(kwargs.get("title", "")),
                "space": {"key": str(kwargs.get("space_key", ""))},
                "body": {
                    "storage": {
                        "value": str(kwargs.get("content", "")),
                        "representation": "storage",
                    }
                },
            }
            data = self._request_json(
                record=record, method="POST", path="/wiki/rest/api/content", body=body
            )
            return ToolOutput(
                text=f"Confluence page created: {data.get('title', '')}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "page": data,
                },
            )
        raise ValueError(f"Unsupported Confluence action: {action}")
