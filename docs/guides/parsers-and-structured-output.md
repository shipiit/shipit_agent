# Parsers & Structured Output

SHIPIT provides a complete output parsing system and first-class structured output support. Get typed, validated responses from LLMs with minimal code.

## Structured Output — One Parameter

Add `output_schema` to any `agent.run()` call. Works with Pydantic models or raw JSON schemas.

### With Pydantic (returns typed instance)

```python
from pydantic import BaseModel
from shipit_agent import Agent

class MovieReview(BaseModel):
    title: str
    rating: float
    summary: str
    pros: list[str]
    cons: list[str]

agent = Agent.with_builtins(llm=llm)
result = agent.run("Review The Matrix", output_schema=MovieReview)

review = result.parsed           # MovieReview instance
review.title                     # "The Matrix"
review.rating                    # 9.5
review.pros                      # ["Groundbreaking visuals", ...]
type(review)                     # <class 'MovieReview'>
```

### With JSON Schema (returns dict, no Pydantic needed)

```python
result = agent.run(
    "Analyze sentiment of: 'Amazing product, love it!'",
    output_schema={
        "type": "object",
        "properties": {
            "sentiment": {"type": "string"},
            "confidence": {"type": "number"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["sentiment", "confidence"],
    },
)

result.parsed                    # {"sentiment": "positive", "confidence": 0.95, ...}
result.parsed["sentiment"]       # "positive"
```

### How it works internally

1. Detects if `output_schema` is a Pydantic model or a dict
2. Appends JSON schema instructions to the system prompt
3. Agent runs normally (can still use tools)
4. Final output is parsed and validated
5. If parsing fails, `result.parsed` is `None` (agent doesn't crash)
6. The raw text is always available in `result.output`

---

## Output Parsers

Standalone parsers for post-processing LLM output. Use them anywhere — with or without agents.

### JSONParser

Handles common LLM quirks: markdown code fences, surrounding prose, and JSON embedded in text.

```python
from shipit_agent.parsers import JSONParser

parser = JSONParser()

# Plain JSON
parser.parse('{"status": "ok"}')
# {"status": "ok"}

# JSON in markdown code fence
parser.parse('Here is the result:\n```json\n{"status": "ok"}\n```\nDone.')
# {"status": "ok"}

# JSON surrounded by prose
parser.parse('The answer is {"value": 42} and that is final.')
# {"value": 42}

# With schema validation
parser = JSONParser(schema={
    "properties": {"name": {}, "age": {}},
    "required": ["name"],
})
parser.parse('{"name": "Alice", "age": 30}')  # OK
parser.parse('{"age": 30}')  # raises ParseError: Missing required key: name
```

### PydanticParser

Parse directly into Pydantic model instances:

```python
from pydantic import BaseModel
from shipit_agent.parsers import PydanticParser

class User(BaseModel):
    name: str
    email: str
    age: int

parser = PydanticParser(model=User)
user = parser.parse('{"name": "Alice", "email": "alice@example.com", "age": 30}')
# User(name='Alice', email='alice@example.com', age=30)

# Auto-generates format instructions for the LLM
print(parser.get_format_instructions())
# "Respond with valid JSON matching this schema: ..."

# Get the raw JSON schema
schema = parser.get_json_schema()
# {"properties": {"name": {"type": "string"}, ...}, "required": [...]}
```

### RegexParser

Extract structured data using regex patterns:

```python
from shipit_agent.parsers import RegexParser

# Named groups
parser = RegexParser(
    pattern=r"Score: (\d+)/10",
    output_keys=["score"],
)
parser.parse("The movie gets a Score: 8/10")
# {"score": "8"}

# Multiple groups
parser = RegexParser(
    pattern=r"(\w+)@(\w+)\.(\w+)",
    output_keys=["user", "domain", "tld"],
)
parser.parse("Contact: admin@example.com")
# {"user": "admin", "domain": "example", "tld": "com"}

# Without keys (numbered groups)
parser = RegexParser(pattern=r"(\d+)-(\d+)")
parser.parse("Range: 10-20")
# {"0": "10", "1": "20"}
```

### MarkdownParser

Extract structured content from markdown-formatted output:

```python
from shipit_agent.parsers import MarkdownParser

parser = MarkdownParser()
result = parser.parse('''
# Analysis Report

## Key Findings
- Revenue increased 15%
- Customer satisfaction at 92%

## Code Example
```python
import pandas as pd
df = pd.read_csv("sales.csv")
```

## Conclusion
- Positive outlook for Q1
''')

result.headings
# [{"level": "1", "text": "Analysis Report"},
#  {"level": "2", "text": "Key Findings"},
#  {"level": "2", "text": "Code Example"},
#  {"level": "2", "text": "Conclusion"}]

result.code_blocks
# [{"language": "python", "code": "import pandas as pd\ndf = pd.read_csv(\"sales.csv\")"}]

result.lists
# ["Revenue increased 15%", "Customer satisfaction at 92%", "Positive outlook for Q1"]
```

## Error Handling

All parsers raise `ParseError` on failure:

```python
from shipit_agent.parsers import JSONParser, ParseError

parser = JSONParser()
try:
    parser.parse("not valid json")
except ParseError as e:
    print(e)            # "Invalid JSON: ..."
    print(e.raw_text)   # "not valid json"
```

## Comparison with LangChain

| Feature | LangChain | SHIPIT |
|---|---|---|
| Structured output | `chain.with_structured_output(Model)` | `agent.run(prompt, output_schema=Model)` |
| JSON parser | `JsonOutputParser()` + chain | `JSONParser().parse(text)` |
| Pydantic parser | `PydanticOutputParser(pydantic_object=...)` | `PydanticParser(model=...)` |
| Regex parser | `RegexParser(regex=...)` | `RegexParser(pattern=...)` |
| Markdown parser | Not built-in | `MarkdownParser()` |
| Code fences handling | Manual | Automatic in JSONParser |
| Error type | Various | Always `ParseError` |
| Works without chains | No (needs LCEL) | Yes (standalone) |
