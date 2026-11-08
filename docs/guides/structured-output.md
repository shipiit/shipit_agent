---
description: Get answers as validated Pydantic objects or JSON, from an agent run, a single model call or a stream.
---

# Structured output

Ask for a shape and get it back validated. Pass a Pydantic model or a JSON Schema, and the answer arrives in `result.parsed`. An answer that does not fit is sent back to the model with the error, in the same conversation, until it does.

## From an agent run

```python
from pydantic import BaseModel

from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env


class Finding(BaseModel):
    file: str
    line: int
    problem: str
    severity: str


class Review(BaseModel):
    summary: str
    findings: list[Finding]


agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")
result = agent.run("Review src/payments for bugs.", output_schema=Review)

for finding in result.parsed.findings:
    print(f"{finding.file}:{finding.line} [{finding.severity}] {finding.problem}")
```

The agent still uses its tools to do the work; only the final answer has to fit the schema. A JSON Schema dict works the same way, and `parsed` is then a dict.

`max_validation_retries` (2 by default) is how many corrections the model gets. If the answer still does not validate, `parsed` is `None` and `output` holds the last text.

With the SDK API, the schema goes in `output_format`, and the result is `ResultMessage.structured_output`:

```python
from shipit_agent.sdk import AgentOptions

options = AgentOptions(output_format={"type": "json_schema", "schema": Review.model_json_schema()})
```

## How a correction works

```text
user:       Review src/payments for bugs. <the schema>
assistant:  I found two problems: the refund path...      ← not JSON
user:       That response could not be parsed: Invalid JSON. Answer with JSON matching the schema.
assistant:  {"summary": "Two bugs...", "findings": [...]}  ← validates
```

The correction stays in the same conversation, so the model fixes its own answer with everything it already found, instead of starting over.

## Without an agent

For extraction or classification that needs no tools, `StructuredOutput` calls the model directly:

```python
from pydantic import BaseModel

from shipit_agent import StructuredOutput
from shipit_agent.llms import build_llm_from_env


class Ticket(BaseModel):
    category: str
    priority: str
    customer_email: str


extract = StructuredOutput(llm=build_llm_from_env(), schema=Ticket, max_retries=2)
result = extract.run("From: ana@shop.com. Checkout charges me twice since this morning!!")

print(result.value)     # Ticket(category='billing', priority='high', customer_email='ana@shop.com')
print(result.attempts)  # 1 when the first answer validated
```

`result.raw_text` is the model's final text and `result.history` the failed attempts. `coerce=True` (the default) lets Pydantic convert compatible types, such as `"3"` for an `int` field.

## Streaming partial JSON

`stream()` yields the object as it fills in, so an interface can show fields as they arrive. Each yield has at least what the one before had; the last is the validated object.

```python
for partial in extract.stream("Classify: the app crashes when I upload a photo."):
    print(partial)
```

```text
{}
{'category': 'bug'}
{'category': 'bug', 'priority': 'med'}
{'category': 'bug', 'priority': 'medium', 'customer_email': ''}
Ticket(category='bug', priority='medium', customer_email='')
```

`parse_partial_json()` does the same for any text stream:

```python
from shipit_agent.parsers import parse_partial_json

parse_partial_json('{"name": "Al')          # {'name': 'Al'}
parse_partial_json('{"items": [1, 2, ')     # {'items': [1, 2]}
parse_partial_json('Sure! Here: {"a": 1}')  # {'a': 1}
```

## Provider-native formats

Calling a model adapter directly, `response_format` passes the provider's own structured-output setting through, such as OpenAI's `{"type": "json_schema", ...}`. Prefer `output_schema` and `StructuredOutput`, which validate the answer and work with every provider.

## See also

- [Parsers](parsers-and-structured-output.md): JSON, Markdown and Pydantic parsers for text you already have.
