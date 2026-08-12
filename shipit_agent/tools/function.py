from __future__ import annotations

import inspect
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Callable

from shipit_agent.prompts import FUNCTION_TOOL_PROMPT
from .base import ToolContext, ToolOutput, ToolRunOutput


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect._empty:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation in (dict,):
        return "object"
    if annotation in (list, tuple, set):
        return "array"
    return "string"


@dataclass(slots=True)
class FunctionTool:
    name: str
    description: str
    func: Callable[..., Any]
    prompt_instructions: str = (
        "Use this when a direct callable can complete the task reliably."
    )
    prompt: str = FUNCTION_TOOL_PROMPT
    #: Declare a pure/side-effect-free function so the runtime may run it
    #: concurrently with other reads. ``None`` (default) leaves the decision
    #: to the name-based contract heuristic — declaring it only overrides.
    read_only: bool | None = None

    @classmethod
    def from_callable(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        read_only: bool | None = None,
    ) -> "FunctionTool":
        return cls(
            name=name or func.__name__,
            description=description
            or inspect.getdoc(func)
            or f"Function tool for {func.__name__}",
            func=func,
            read_only=read_only,
        )

    def schema(self) -> dict[str, Any]:
        signature = inspect.signature(self.func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in signature.parameters.items():
            if param_name == "context":
                continue
            # *args / **kwargs are not parameters the model can supply. They
            # have no default, so they were being advertised as *required* —
            # telling the model to invent a value for `**_ignored`, and
            # making the declared `required` list unusable for validation.
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            properties[param_name] = {
                "type": _annotation_name(param.annotation),
                "description": f"Argument {param_name}",
            }
            if param.default is inspect._empty:
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolRunOutput:
        signature = inspect.signature(self.func)
        if "context" in signature.parameters:
            result = self.func(context=context, **kwargs)
        else:
            result = self.func(**kwargs)

        if isinstance(result, ToolOutput):
            return result
        # Preserve generators so the runtime can publish each tool-output
        # chunk as it arrives instead of stringifying the generator object.
        if isinstance(result, Iterator):
            return result
        if result is None:
            return ToolOutput(text="")
        return ToolOutput(text=str(result))
