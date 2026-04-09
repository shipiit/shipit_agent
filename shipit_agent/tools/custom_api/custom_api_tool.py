from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import CUSTOM_API_PROMPT


class CustomAPITool(HTTPConnectorToolBase):
    provider = "custom_api"

    def __init__(self, *, credential_key: str = "custom_api", credential_store=None, name: str = "custom_api", description: str = "Call a configured custom HTTP API.", prompt: str | None = None) -> None:
        super().__init__(credential_key=credential_key, credential_store=credential_store)
        self.name = name
        self.description = description
        self.prompt = prompt or CUSTOM_API_PROMPT
        self.prompt_instructions = "Use this for custom internal APIs or external APIs that are not yet wrapped by a dedicated tool."

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": {"type": "string"}, "query": {"type": "object"}, "body": {"type": "object"}}, "required": ["method", "path"]}}}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output()
        data = self._request_json(record=record, method=str(kwargs.get("method", "GET")), path=str(kwargs.get("path", "")), query=kwargs.get("query"), body=kwargs.get("body"))
        return ToolOutput(text=str(data), metadata={"provider": self.provider, "connected": True, "response": data})
