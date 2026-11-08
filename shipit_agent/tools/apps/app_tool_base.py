"""Shared base for the app tools."""

from __future__ import annotations

from shipit_agent.apps import (
    AppStore,
)

_MAX_OUTPUT = 12_000


class _AppTool:
    """Shared plumbing: one store, one description of where apps live."""

    def __init__(self, store: AppStore) -> None:
        self.store = store
        self.prompt_instructions = ""

    @staticmethod
    def _function(name: str, description: str, properties: dict, required: list):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

