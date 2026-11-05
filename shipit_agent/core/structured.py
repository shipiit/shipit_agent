from __future__ import annotations

import json
from typing import Any

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser
from shipit_agent.parsers.pydantic_parser import PydanticParser


def is_pydantic_model(obj: Any) -> bool:
    """Check if obj is a Pydantic model class."""
    try:
        return hasattr(obj, "model_json_schema") and hasattr(obj, "model_validate")
    except Exception:
        return False


def schema_to_response_format(schema: Any) -> dict[str, Any]:
    """Convert an output_schema (Pydantic model or dict) to a response_format dict."""
    if is_pydantic_model(schema):
        json_schema = schema.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": getattr(schema, "__name__", "output"),
                "schema": json_schema,
            },
        }
    if isinstance(schema, dict):
        return {"type": "json_object"}
    return {}


def build_schema_prompt(schema: Any) -> str:
    """Build a prompt addition that instructs the LLM to output structured JSON."""
    if is_pydantic_model(schema):
        json_schema = schema.model_json_schema()
        return (
            "\n\nRespond with a JSON object matching this schema:\n"
            f"```json\n{json.dumps(json_schema, indent=2)}\n```"
        )
    if isinstance(schema, dict):
        return (
            "\n\nRespond with a JSON object matching this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```"
        )
    return ""


def parse_structured_output(text: str, schema: Any) -> Any:
    """Parse LLM output text according to the given schema.

    Returns a Pydantic model instance if schema is a Pydantic model,
    or a dict/list if schema is a JSON schema dict.
    """
    if is_pydantic_model(schema):
        parser = PydanticParser(model=schema)
        return parser.parse(text)
    if isinstance(schema, dict):
        parser = JSONParser(schema=schema)
        return parser.parse(text)
    raise ParseError(f"Unsupported schema type: {type(schema)}", raw_text=text)
