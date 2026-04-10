"""
08 — Structured Output

Get typed, validated responses from LLMs using Pydantic models or JSON schemas.
One parameter on agent.run() — cleaner than LangChain.

Run:
    python examples/08_structured_output.py

Requires:
    pip install 'shipit-agent[all]'
    AWS credentials or SHIPIT_LLM_PROVIDER in .env
"""
from __future__ import annotations

from pydantic import BaseModel

from examples.run_multi_tool_agent import build_llm_from_env
from shipit_agent import Agent


class CompanyAnalysis(BaseModel):
    company: str
    industry: str
    strengths: list[str]
    weaknesses: list[str]
    recommendation: str


def main() -> None:
    llm = build_llm_from_env()
    agent = Agent(llm=llm, name="analyst")

    # --- Pydantic model: returns typed instance ---
    print("=== Pydantic Structured Output ===\n")
    result = agent.run(
        "Analyze Apple Inc as a company",
        output_schema=CompanyAnalysis,
    )

    if result.parsed:
        analysis = result.parsed
        print(f"Company:        {analysis.company}")
        print(f"Industry:       {analysis.industry}")
        print(f"Strengths:      {analysis.strengths}")
        print(f"Weaknesses:     {analysis.weaknesses}")
        print(f"Recommendation: {analysis.recommendation}")
    else:
        print(f"Raw output: {result.output[:200]}")

    # --- JSON schema: returns dict ---
    print("\n=== JSON Schema Structured Output ===\n")
    result = agent.run(
        "List the top 3 programming languages for web development",
        output_schema={
            "type": "object",
            "properties": {
                "languages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "use_case": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["languages"],
        },
    )

    if result.parsed:
        for lang in result.parsed["languages"]:
            print(f"  {lang.get('name', '?'):15s} — {lang.get('use_case', '?')}")
    else:
        print(f"Raw output: {result.output[:200]}")


if __name__ == "__main__":
    main()
