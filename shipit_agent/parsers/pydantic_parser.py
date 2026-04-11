from __future__ import annotations

import json
from typing import Any, TypeVar

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser

T = TypeVar("T")


class PydanticParser:
    """Parse LLM output into a Pydantic model instance.

    Example::

        from pydantic import BaseModel

        class Movie(BaseModel):
            title: str
            rating: float

        parser = PydanticParser(model=Movie)
        movie = parser.parse('{"title": "The Matrix", "rating": 9.5}')
        # Movie(title='The Matrix', rating=9.5)
    """

    def __init__(self, *, model: type) -> None:
        self.model = model
        self._json_parser = JSONParser()

    def parse(self, text: str) -> Any:
        data = self._json_parser.parse(text)
        try:
            return (
                self.model(**data)
                if isinstance(data, dict)
                else self.model.model_validate(data)
            )
        except Exception as exc:
            raise ParseError(
                f"Pydantic validation failed: {exc}", raw_text=text
            ) from exc

    def get_format_instructions(self) -> str:
        try:
            schema = self.model.model_json_schema()
        except AttributeError:
            # Fallback for non-Pydantic classes with __annotations__
            schema = {
                "type": "object",
                "properties": {
                    k: {"type": "string"}
                    for k in getattr(self.model, "__annotations__", {})
                },
            }
        return f"Respond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"

    def get_json_schema(self) -> dict[str, Any]:
        """Return the JSON schema for the Pydantic model."""
        try:
            return self.model.model_json_schema()
        except AttributeError:
            return {"type": "object", "properties": {}}
