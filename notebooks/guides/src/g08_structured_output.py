"""Guide 08: structured output, from agent runs and single calls."""

from cells import code, md

TITLE = "Structured output"

CELLS = [
    md("""
    # Guide 08 · Structured output

    Ask for a shape, get it back validated. Pass a Pydantic model (or a JSON Schema) and the answer arrives as a
    typed object. An answer that doesn't fit goes back to the model with the validation error, in the same
    conversation, until it does.

    **What you'll learn**

    1. `output_schema=` on an agent run, and `result.parsed`
    2. Nested models, lists, enums and constraints
    3. An agent that uses tools, then answers in a schema
    4. Validation retries, and what happens when they run out
    5. `StructuredOutput` for a single call with no agent, and streaming partial objects
    6. JSON Schema instead of Pydantic, and the building blocks underneath

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · A typed answer from a run

    Pass the model class as `output_schema`. The typed object is `result.parsed`; `result.output` keeps the text.
    """),
    code("""
    from pydantic import BaseModel

    class Ticket(BaseModel):
        category: str
        priority: str
        customer_email: str

    result = Agent(llm=haiku).run(
        "From: ana@example.com — Checkout charges me twice since this morning!!", output_schema=Ticket)
    print(repr(result.parsed))
    print(type(result.parsed).__name__, "| priority:", result.parsed.priority)
    """),
    md("""
    ## 3 · Nested models, lists, enums and constraints

    Everything Pydantic validates is enforced: here an enum for severity, a list of findings, and a bounded
    score.
    """),
    code("""
    from enum import Enum

    from pydantic import Field

    class Severity(str, Enum):
        low = "low"
        medium = "medium"
        high = "high"

    class Finding(BaseModel):
        line: int
        problem: str
        severity: Severity

    class Review(BaseModel):
        summary: str = Field(max_length=200)
        findings: list[Finding]
        score: int = Field(ge=0, le=10, description="Overall quality, 0 to 10")

    SNIPPET = '''
    1  def charge(amount, card):
    2      fee = amount * 0.029 + 0.30
    3      total = round(amount + fee, 2)
    4      if card.balance > total:
    5          card.balance -= total
    6      return total
    '''
    review = Agent(llm=haiku).run(f"Review this payment code:\\n{SNIPPET}", output_schema=Review).parsed
    print(f"score {review.score}/10 — {review.summary}")
    for f in review.findings:
        print(f"  line {f.line:2} [{f.severity.value:6}] {f.problem}")
    """),
    md("""
    ## 4 · Tools first, then a typed answer

    The agent can use its tools along the way; only the final answer has to fit the schema.
    """),
    code("""
    import json

    from shipit_agent.tools import FunctionTool

    ACCOUNTS = {"acme": {"plan": "Team", "seats": 42, "mrr": 1218, "open_tickets": 7},
                "globex": {"plan": "Starter", "seats": 5, "mrr": 60, "open_tickets": 0}}

    def account(name: str) -> str:
        \"\"\"Look up a customer account by name.\"\"\"
        return json.dumps(ACCOUNTS.get(name.lower(), {}))

    class Health(BaseModel):
        account: str
        plan: str
        at_risk: bool
        reason: str

    agent = Agent(llm=haiku, tools=[FunctionTool.from_callable(account, read_only=True)])
    result = agent.run("Is Acme at risk? Look it up.", output_schema=Health)
    print([r.name for r in result.tool_results])
    print(result.parsed)
    """),
    md("""
    ## 5 · Validation retries

    If the answer doesn't validate, the error goes back to the model and it tries again, up to
    `max_validation_retries` (2 by default). A custom check, an exact word count, is enforced the same way;
    here the first answer already fit.
    """),
    code("""
    class Slogan(BaseModel):
        text: str = Field(description="Exactly five words")

        def model_post_init(self, _):
            if len(self.text.split()) != 5:
                raise ValueError(f"text must be exactly 5 words, got {len(self.text.split())}")

    result = Agent(llm=haiku).run("A slogan for a sandboxed AI agent runtime.", output_schema=Slogan)
    print(result.parsed)
    print("model turns:", sum(1 for m in result.messages if m.role == "assistant"))
    """),
    md("""
    ## 6 · When retries run out

    An impossible constraint: once the retries are used up, `run()` raises, with the last validation error and
    the model's own text, so your code can decide what to do.
    """),
    code("""
    class Impossible(BaseModel):
        n: int = Field(gt=10, lt=5)

    try:
        Agent(llm=haiku).run("Give me a number.", output_schema=Impossible, max_validation_retries=1)
    except Exception as error:
        print(type(error).__name__)
        print(str(error)[:400])
    """),
    md("""
    ## 7 · No agent: `StructuredOutput`

    For extraction or classification with no tools, call the model directly. The result has the `value`, the
    `attempts` it took, the `raw_text`, and the failed attempts in `history`.
    """),
    code("""
    from shipit_agent import StructuredOutput

    extract = StructuredOutput(llm=haiku, schema=Ticket, max_retries=2)
    emails = [
        "From: ana@example.com. Checkout charges me twice since this morning!!",
        "lin@example.org here — could you add dark mode at some point? No rush.",
        "From raj@example.net: the export button 500s for every report. Board meeting in an hour.",
    ]
    for email in emails:
        r = extract.run(email)
        print(f"{r.value.priority:7} {r.value.category:16} {r.value.customer_email:16} attempts={r.attempts}")
    """),
    md("""
    ## 8 · Stream the object as it fills in

    `stream()` yields the object as it's written; each yield has at least what the one before had, and the last
    is the validated object.
    """),
    code("""
    for partial in extract.stream("From mo@example.com: the app crashes when I upload a photo."):
        print(partial)
    """),
    md("""
    ## 9 · Partial JSON from any text

    `parse_partial_json` reads whatever valid prefix a stream has so far, and skips chatter around the JSON.
    """),
    code("""
    from shipit_agent.parsers import parse_partial_json

    for text in ['{"name": "Al', '{"items": [1, 2, ', 'Sure! Here: {"a": 1}', '{"a": {"b": [true, nu']:
        print(f"{text!r:28} -> {parse_partial_json(text)}")
    """),
    md("""
    ## 10 · JSON Schema instead of Pydantic

    A plain JSON Schema dict works too; the parsed value is a dict.
    """),
    code("""
    schema = {
        "type": "object",
        "properties": {
            "language": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["language", "confidence"],
    }
    result = Agent(llm=haiku).run("Which language is this: 'Wo ist der Bahnhof?'", output_schema=schema)
    print(result.parsed, type(result.parsed).__name__)
    """),
    md("""
    ## 11 · The building blocks

    `StructuredOutput` and `output_schema=` are made of three helpers you can use with your own model calls.
    """),
    code("""
    from shipit_agent import build_schema_prompt, parse_structured_output, schema_to_response_format

    print(build_schema_prompt(Ticket)[:300], "…\\n")
    print(json.dumps(schema_to_response_format(Ticket))[:200], "…\\n")
    print(parse_structured_output('Here you go: {"category": "billing", "priority": "high", "customer_email": "a@example.com"}', Ticket))
    try:
        parse_structured_output('{"category": "billing"}', Ticket)
    except Exception as error:
        print(type(error).__name__, "->", str(error)[:120])
    """),
    md("""
    ## 12 · The same schemas on Gemma 4
    """),
    code("""
    review = Agent(llm=gemma).run(f"Review this payment code:\\n{SNIPPET}", output_schema=Review).parsed
    print(f"score {review.score}/10 — {review.summary}")
    for f in review.findings:
        print(f"  line {f.line:2} [{f.severity.value:6}] {f.problem}")

    r = StructuredOutput(llm=gemma, schema=Ticket).run(emails[2])
    print("\\n", r.value, "| attempts:", r.attempts)
    """),
    md("""
    ## 13 · Summary

    - `run(..., output_schema=Model)` returns the typed answer in `result.parsed`, after any tool use.
    - Pydantic constraints are enforced; failures go back to the model up to `max_validation_retries`.
    - When retries run out, `run()` raises with the last error and the model's text.
    - `StructuredOutput` does single calls, with `stream()` for partial objects.
    - JSON Schema dicts work too; `build_schema_prompt`, `schema_to_response_format` and
      `parse_structured_output` are the parts underneath.

    **Next:** Guide 09 — permissions, hooks and the sandbox.
    """),
]
