from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from shipit_agent.prompts import FUNCTION_TOOL_PROMPT
from .base import ToolContext, ToolOutput


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
    prompt_instructions: str = "Use this when a direct callable can complete the task reliably."
    prompt: str = FUNCTION_TOOL_PROMPT

    @classmethod
    def from_callable(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> "FunctionTool":
        return cls(
            name=name or func.__name__,
            description=description or inspect.getdoc(func) or f"Function tool for {func.__name__}",
            func=func,
        )

    def schema(self) -> dict[str, Any]:
        signature = inspect.signature(self.func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in signature.parameters.items():
            if param_name == "context":
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

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        signature = inspect.signature(self.func)
        if "context" in signature.parameters:
            result = self.func(context=context, **kwargs)
        else:
            result = self.func(**kwargs)

        if isinstance(result, ToolOutput):
            return result
        if result is None:
            return ToolOutput(text="")
        return ToolOutput(text=str(result))
