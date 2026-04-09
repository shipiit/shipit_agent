from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import NOTION_PROMPT


class NotionTool(HTTPConnectorToolBase):
    provider = "notion"

    def __init__(self, *, credential_key: str = "notion", credential_store=None, name: str = "notion", description: str = "Search Notion pages and create Notion pages.", prompt: str | None = None) -> None:
        super().__init__(credential_key=credential_key, credential_store=credential_store)
        self.name = name
        self.description = description
        self.prompt = prompt or NOTION_PROMPT
        self.prompt_instructions = "Use this for Notion page search and page creation."

    def _headers(self, record):
        headers = super()._headers(record)
        headers["Notion-Version"] = str(record.metadata.get("notion_version", "2022-06-28"))
        return headers

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["search_pages", "create_page"], "default": "search_pages"}, "query": {"type": "string"}, "parent_page_id": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "string"}}, "required": ["action"]}}}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_pages"))
        if action == "search_pages":
            data = self._request_json(record=record, method="POST", path="/v1/search", body={"query": str(kwargs.get("query", "")), "page_size": 10})
            items = data.get("results", [])
            return ToolOutput(text="\n".join(item.get("url", "") for item in items) if items else "No Notion pages found.", metadata={"provider": self.provider, "connected": True, "action": action, "items": items, "count": len(items)})
        if action == "create_page":
            body = {"parent": {"page_id": str(kwargs.get("parent_page_id", ""))}, "properties": {"title": {"title": [{"text": {"content": str(kwargs.get("title", ""))}}]}}, "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": str(kwargs.get("content", ""))}}]}}]}
            data = self._request_json(record=record, method="POST", path="/v1/pages", body=body)
            return ToolOutput(text=f"Notion page created: {data.get('url', '')}", metadata={"provider": self.provider, "connected": True, "action": action, "page": data})
        raise ValueError(f"Unsupported Notion action: {action}")
