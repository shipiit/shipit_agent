"""Reading what an SDK ``@tool`` handler returned, and the schema it declared."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, NotRequired, Required, get_args, get_origin, get_type_hints

from shipit_agent.tools.base import ToolOutput

__all__ = ["ToolAnnotations", "annotation_dict", "json_schema", "to_output"]

#: Image types every vision model reads; any other is described in words.
_SEEN_IMAGES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclasses.dataclass(slots=True)
class ToolAnnotations:
    """How a tool behaves, in MCP's terms. ``readOnlyHint`` lets calls run in parallel."""

    title: str | None = None
    readOnlyHint: bool | None = None
    destructiveHint: bool | None = None
    idempotentHint: bool | None = None
    openWorldHint: bool | None = None


def annotation_dict(annotations: Any) -> dict[str, Any]:
    """Annotations as a dict, whether given as one or as a :class:`ToolAnnotations`."""
    if annotations is None:
        return {}
    if isinstance(annotations, dict):
        return dict(annotations)
    if dataclasses.is_dataclass(annotations) and not isinstance(annotations, type):
        return {key: value for key, value in dataclasses.asdict(annotations).items() if value is not None}
    raise TypeError("annotations must be a dict or a ToolAnnotations")


def _property(kind: Any) -> dict[str, Any]:
    description = None
    if get_origin(kind) in (NotRequired, Required):
        kind = get_args(kind)[0]
    if get_origin(kind) is Annotated:
        kind, *extras = get_args(kind)
        description = next((extra for extra in extras if isinstance(extra, str)), None)
    schema: dict[str, Any] = {"type": _JSON_TYPES.get(get_origin(kind) or kind, "string")}
    if description:
        schema["description"] = description
    return schema


def json_schema(spec: Any) -> dict[str, Any]:
    """A JSON Schema from a full schema, a ``{"name": type}`` mapping or a ``TypedDict``.

    A type wrapped in ``Annotated[type, "..."]`` gives the field its description.
    """
    if isinstance(spec, type) and hasattr(spec, "__required_keys__"):
        hints = get_type_hints(spec, include_extras=True)
        # Read from the resolved hints: with postponed annotations the class
        # itself cannot tell which keys were marked NotRequired.
        total = bool(getattr(spec, "__total__", True))
        required = [
            name
            for name, kind in hints.items()
            if get_origin(kind) is Required or (total and get_origin(kind) is not NotRequired)
        ]
        return {"type": "object", "properties": {name: _property(kind) for name, kind in hints.items()}, "required": required}
    if not isinstance(spec, dict):
        raise TypeError("input_schema must be a dict or a TypedDict class")
    if spec.get("type") == "object" or "properties" in spec:
        return dict(spec)
    return {"type": "object", "properties": {key: _property(kind) for key, kind in spec.items()}, "required": list(spec)}


def _resource_text(block: dict[str, Any]) -> str:
    resource = block.get("resource")
    if not isinstance(resource, dict):
        return ""
    uri = str(resource.get("uri") or "resource")
    if isinstance(resource.get("text"), str):
        return f"[{uri}]\n{resource['text']}"
    return f"[{uri}: binary content not shown]"


def to_output(result: Any) -> ToolOutput:
    """A handler's ``{"content": [...]}`` as a tool result.

    Text, resource and link blocks become the text. The first PNG, JPEG, GIF
    or WebP image is shown to the model as an image; the blocks themselves and
    any ``structuredContent`` stay in the result's metadata for callers.
    """
    if not isinstance(result, dict):
        return ToolOutput(text=str(result))
    blocks = [block for block in result.get("content") or [] if isinstance(block, dict)]
    parts: list[str] = []
    metadata: dict[str, Any] = {}
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text", "")))
        elif kind == "resource":
            parts.append(_resource_text(block))
        elif kind == "resource_link":
            label = f"{block.get('name') or 'link'} ({block.get('uri', '')})"
            parts.append(f"{label}: {block['description']}" if block.get("description") else label)
        elif kind == "image":
            media_type = str(block.get("mimeType") or block.get("mime_type") or "image/png")
            if media_type not in _SEEN_IMAGES or not block.get("data"):
                parts.append(f"[{media_type} image not shown]")
            elif "image_base64" not in metadata:
                metadata.update(image_base64=str(block["data"]), media_type=media_type, vision=True)
    if blocks:
        metadata["content_blocks"] = blocks
    if result.get("structuredContent") is not None:
        metadata["structured_content"] = result["structuredContent"]
    if result.get("is_error") or result.get("isError"):
        metadata["is_error"] = True
    return ToolOutput(text="\n".join(part for part in parts if part), metadata=metadata)
