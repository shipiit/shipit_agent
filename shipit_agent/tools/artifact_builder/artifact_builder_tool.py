from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import ARTIFACT_BUILDER_PROMPT


class ArtifactBuilderTool:
    def __init__(
        self,
        *,
        name: str = "build_artifact",
        description: str = "Create a named artifact such as a report, markdown document, JSON blob, or code file.",
        prompt: str | None = None,
        workspace_root: str | Path = ".shipit_workspace/artifacts",
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or ARTIFACT_BUILDER_PROMPT
        self.workspace_root = Path(workspace_root)
        self.prompt_instructions = "Use this when the user needs a structured deliverable rather than only conversational text."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Artifact name"},
                        "content": {
                            "type": "string",
                            "description": "Artifact content",
                        },
                        "media_type": {
                            "type": "string",
                            "description": "Artifact media type",
                            "default": "text/plain",
                        },
                        "export": {
                            "type": "boolean",
                            "description": "Whether to save the artifact to a file",
                        },
                        "path": {
                            "type": "string",
                            "description": "Optional relative export path",
                        },
                    },
                    "required": ["name", "content"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        artifact = {
            "name": kwargs["name"],
            "content": kwargs["content"],
            "media_type": kwargs.get("media_type", "text/plain"),
        }
        if kwargs.get("export"):
            root = Path(
                context.state.get("artifact_workspace_root", self.workspace_root)
            )
            root.mkdir(parents=True, exist_ok=True)
            relative_path = Path(str(kwargs.get("path", artifact["name"])))
            export_path = (root / relative_path).resolve()
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(artifact["content"], encoding="utf-8")
            artifact["path"] = str(export_path)
        context.state.setdefault("artifacts", []).append(artifact)
        return ToolOutput(
            text=f"Artifact created: {artifact['name']}",
            metadata={"artifact": artifact},
        )
