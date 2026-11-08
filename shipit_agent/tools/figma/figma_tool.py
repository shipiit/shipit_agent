"""The ``figma`` tool: read Figma files, render node images, browse and post comments, and introspect team projects / components via the Figma REST API.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .comments_teams import _CommentTeamActions
from .constants import _VALID_IMAGE_FORMATS
from .files import _FileActions
from .http_helpers import _FigmaHTTP
from .prompt import FIGMA_PROMPT

_ACTIONS = [
    "get_file",
    "get_file_nodes",
    "get_image",
    "get_comments",
    "post_comment",
    "resolve_comment",
    "get_team_projects",
    "get_project_files",
    "get_team_components",
]


class FigmaTool(_FigmaHTTP, _FileActions, _CommentTeamActions, HTTPConnectorToolBase):
    """The ``figma`` tool: read Figma files, render node images, browse and post comments, and introspect team projects / components via the Figma REST API.
    """
    provider = "figma"

    def __init__(
        self,
        *,
        credential_key: str = "figma",
        credential_store: Any = None,
        name: str = "figma",
        description: str = (
            "Read Figma files, render node images, browse and post comments, and "
            "introspect team projects / components via the Figma REST API."
        ),
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or FIGMA_PROMPT
        self.prompt_instructions = (
            "Use this for reading Figma file structure, rendering node images, "
            "managing design-review comments, and browsing team / project / "
            "component libraries."
        )

    # ------------------------------------------------------------------ schema

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
                            "enum": list(_ACTIONS),
                            "default": "get_file",
                        },
                        "file_key": {"type": "string"},
                        "team_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "comment_id": {"type": "string"},
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "format": {
                            "type": "string",
                            "enum": sorted(_VALID_IMAGE_FORMATS),
                            "default": "png",
                        },
                        "scale": {"type": "number", "default": 1},
                        "message": {"type": "string"},
                        "client_meta": {
                            "type": "object",
                            "description": (
                                "Either {'node_id': str, 'node_offset': {'x': n, 'y': n}} "
                                "or {'x': n, 'y': n} to pin a comment."
                            ),
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------- run

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
        record = self._ensure_base_url(record)

        action = str(kwargs.get("action", "get_file")).strip()

        handlers = {
            "get_file": self._get_file,
            "get_file_nodes": self._get_file_nodes,
            "get_image": self._get_image,
            "get_comments": self._get_comments,
            "post_comment": self._post_comment,
            "resolve_comment": self._resolve_comment,
            "get_team_projects": self._get_team_projects,
            "get_project_files": self._get_project_files,
            "get_team_components": self._get_team_components,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolOutput(
                text=f"Figma: unsupported action '{action}'.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "unsupported_action",
                    "action": action,
                },
            )
        return handler(record=record, action=action, kwargs=kwargs)
