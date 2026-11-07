"""The ``build_artifact`` tool: a deliverable with a stable id, versions and in-place updates.

``create`` saves version 1, ``update`` replaces one exact piece of text,
``rewrite`` replaces the whole content; each change is a new version on disk
(see :mod:`.store`), and the run's state records every version so a UI can
preview and offer downloads. The older call shape (``name``, ``media_type``,
``export``, ``path``) still works: without ``export`` it is kept in memory only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from . import store
from .prompt import ARTIFACT_BUILDER_PROMPT

_ACTIONS = ("create", "update", "rewrite")


class ArtifactBuilderTool:
    """The ``build_artifact`` tool: a deliverable with a stable id, versions and in-place updates."""

    def __init__(
        self,
        *,
        name: str = "build_artifact",
        description: str = (
            "Create a deliverable (report, page, code, diagram, data) with a stable "
            "id, then update or rewrite it; every change is saved as a new version."
        ),
        prompt: str | None = None,
        workspace_root: str | Path = ".shipit_workspace/artifacts",
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or ARTIFACT_BUILDER_PROMPT
        self.workspace_root = Path(workspace_root)
        self.prompt_instructions = (
            "Use this when the user needs a deliverable rather than only "
            "conversational text; keep one id per deliverable and update it."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Stable short name, e.g. 'q3-report'. Reuse it to change the artifact.",
                        },
                        "action": {
                            "type": "string",
                            "enum": list(_ACTIONS),
                            "description": "create (default), update (replace exact text), or rewrite (replace all).",
                        },
                        "title": {
                            "type": "string",
                            "description": "Human-readable title.",
                        },
                        "type": {
                            "type": "string",
                            "enum": [*store.TYPE_EXTENSIONS, "code"],
                            "description": "What the content is.",
                        },
                        "language": {
                            "type": "string",
                            "description": "For type=code, e.g. 'python'.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full content, for create and rewrite.",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "For update: exact text to replace, unique in the artifact.",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "For update: the replacement.",
                        },
                    },
                    "required": ["id"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        legacy = "id" not in kwargs and "name" in kwargs
        try:
            if legacy:
                return self._legacy(context, kwargs)
            return self._versioned(context, kwargs)
        except store.ArtifactError as exc:
            return ToolOutput.error(f"Artifact not saved: {exc}", error=exc.code)

    # -- the versioned API --------------------------------------------------

    def _versioned(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolOutput:
        artifact_id = store.check_id(str(kwargs.get("id", "")))
        action = str(kwargs.get("action") or "create")
        if action not in _ACTIONS:
            raise store.ArtifactError(
                "invalid_action",
                f"action must be one of {', '.join(_ACTIONS)}, not {action!r}.",
            )
        root = self._root(context)
        current = store.latest(root, artifact_id)
        if action == "create":
            if current is not None:
                raise store.ArtifactError(
                    "already_exists",
                    f"'{artifact_id}' already exists (v{current.version}). Use action=update "
                    "or rewrite to change it, or pick a new id.",
                )
            artifact_type = str(kwargs.get("type") or "text")
            extension = store.extension_for(
                artifact_type, str(kwargs.get("language") or "")
            )
            content = str(kwargs.get("content", ""))
        else:
            if current is None:
                raise store.ArtifactError(
                    "unknown_artifact",
                    f"No artifact '{artifact_id}' yet. Create it first.",
                )
            extension = current.extension
            artifact_type = _type_for(extension)
            content = (
                _replace(current.path.read_text(encoding="utf-8"), kwargs, artifact_id)
                if action == "update"
                else str(kwargs.get("content", ""))
            )
        saved = store.save(root, artifact_id, content, extension)
        record = self._record(
            context, saved, kwargs.get("title") or artifact_id, artifact_type, content
        )
        verb = {"create": "Created", "update": "Updated", "rewrite": "Rewrote"}[action]
        return ToolOutput(
            text=(
                f"{verb} artifact '{artifact_id}' v{saved.version} ({artifact_type}, "
                f"{_lines(content)} lines): {saved.path}"
            ),
            metadata={"artifact": record, "path": str(saved.path)},
        )

    # -- the older call shape -----------------------------------------------

    def _legacy(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolOutput:
        name = str(kwargs["name"])
        content = str(kwargs.get("content", ""))
        media_type = str(kwargs.get("media_type", "text/plain"))
        artifact: dict[str, Any] = {
            "name": name,
            "content": content,
            "media_type": media_type,
        }
        if kwargs.get("export"):
            root = self._root(context)
            artifact_id = store.check_id(Path(name).stem or "artifact")
            artifact_type = store.MEDIA_TYPES.get(media_type, "text")
            extension = Path(name).suffix or store.extension_for(artifact_type)
            saved = store.save(root, artifact_id, content, extension)
            artifact.update(id=artifact_id, version=saved.version, path=str(saved.path))
            if kwargs.get("path"):
                target = store.confined(root, str(kwargs["path"]))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                artifact["path"] = str(target)
        else:
            artifact.update(id=name, version=1)
        context.state.setdefault("artifacts", []).append(artifact)
        return ToolOutput(
            text=f"Artifact created: {name}", metadata={"artifact": artifact}
        )

    # -- helpers --------------------------------------------------------------

    def _root(self, context: ToolContext) -> Path:
        state = getattr(context, "state", None) or {}
        return Path(state.get("artifact_workspace_root", self.workspace_root))

    @staticmethod
    def _record(
        context: ToolContext,
        saved: store.SavedVersion,
        title: Any,
        artifact_type: str,
        content: str,
    ) -> dict[str, Any]:
        record = {
            "id": saved.id,
            "name": saved.id,
            "title": str(title),
            "type": artifact_type,
            "version": saved.version,
            "path": str(saved.path),
            "content": content,
        }
        context.state.setdefault("artifacts", []).append(record)
        return record


def _replace(text: str, kwargs: dict[str, Any], artifact_id: str) -> str:
    old = str(kwargs.get("old_text", ""))
    new = str(kwargs.get("new_text", ""))
    count = text.count(old) if old else 0
    if count == 0:
        raise store.ArtifactError(
            "old_text_not_found",
            f"old_text is not in '{artifact_id}'. Copy the exact text, or use action=rewrite.",
        )
    if count > 1:
        raise store.ArtifactError(
            "old_text_not_unique",
            f"old_text matches {count} places in '{artifact_id}'. Include more "
            "surrounding text so it matches one.",
        )
    return text.replace(old, new, 1)


def _type_for(extension: str) -> str:
    for artifact_type, known in store.TYPE_EXTENSIONS.items():
        if known == extension:
            return artifact_type
    return "code"


def _lines(content: str) -> int:
    return content.count("\n") + (0 if content.endswith("\n") or not content else 1)
