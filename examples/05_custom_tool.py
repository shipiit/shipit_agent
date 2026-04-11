"""
05 — Build and attach a custom tool from scratch.

Shows the full pattern for adding domain-specific capabilities to a shipit
agent without forking the library. Two equivalent approaches:

  A) FunctionTool.from_callable — quickest, wraps a plain Python function
  B) A real Tool class — more control over schema, prompt instructions,
     and ToolOutput metadata

Both end up indexed by tool_search and visible to the LLM identically.

Run:
    python examples/05_custom_tool.py
"""

from __future__ import annotations

import math

from shipit_agent import Agent, FunctionTool
from shipit_agent.tools.base import ToolContext, ToolOutput

from examples.run_multi_tool_agent import build_llm_from_env


# ---------------------------------------------------------------------- #
# Approach A — wrap a plain function
# ---------------------------------------------------------------------- #


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Compute great-circle distance between two GPS coordinates in km."""
    r = 6371.0  # Earth radius (km)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    distance_km = 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return f"{distance_km:.2f} km"


haversine_tool = FunctionTool.from_callable(
    haversine,
    name="haversine_distance",
    description="Calculate great-circle distance in km between two GPS coordinates.",
)


# ---------------------------------------------------------------------- #
# Approach B — full Tool class with rich metadata
# ---------------------------------------------------------------------- #


class CompoundInterestTool:
    """Tool class style — more control over schema and output metadata."""

    name = "compound_interest"
    description = "Calculate compound interest on a principal over a time period."
    prompt_instructions = (
        "Use this for any financial growth question that involves a "
        "principal amount, interest rate, and time period."
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
                        "principal": {
                            "type": "number",
                            "description": "Starting amount in dollars",
                        },
                        "annual_rate_percent": {
                            "type": "number",
                            "description": "Annual interest rate as a percent (e.g. 5.0 for 5%)",
                        },
                        "years": {"type": "number", "description": "Number of years"},
                        "compounds_per_year": {
                            "type": "integer",
                            "description": "How many times per year interest compounds (default 12 = monthly)",
                        },
                    },
                    "required": ["principal", "annual_rate_percent", "years"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        principal = float(kwargs["principal"])
        rate = float(kwargs["annual_rate_percent"]) / 100.0
        years = float(kwargs["years"])
        n = int(kwargs.get("compounds_per_year", 12))

        final = principal * (1 + rate / n) ** (n * years)
        gain = final - principal

        return ToolOutput(
            text=(
                f"Starting with ${principal:,.2f} at {rate * 100:.2f}% annual interest "
                f"compounded {n} times per year for {years} years grows to "
                f"${final:,.2f} (a gain of ${gain:,.2f})."
            ),
            metadata={
                "principal": principal,
                "annual_rate_percent": rate * 100,
                "years": years,
                "compounds_per_year": n,
                "final_amount": round(final, 2),
                "gain": round(gain, 2),
            },
        )


# ---------------------------------------------------------------------- #
# Wire it all up
# ---------------------------------------------------------------------- #


def main() -> None:
    llm = build_llm_from_env()

    agent = Agent(
        llm=llm,
        prompt="You are a quantitative assistant. Use the available tools when needed.",
        tools=[
            haversine_tool,
            CompoundInterestTool(),
        ],
    )

    # Question 1 — uses the function-style tool
    result1 = agent.run(
        "How far apart are San Francisco (37.7749, -122.4194) and "
        "New York City (40.7128, -74.0060)?"
    )
    print("─" * 60)
    print("Q1: SF to NYC distance")
    print("─" * 60)
    print(result1.output)

    # Question 2 — uses the class-style tool
    result2 = agent.run(
        "If I invest $10,000 at 7% annual interest compounded monthly "
        "for 30 years, how much will I have?"
    )
    print("\n" + "─" * 60)
    print("Q2: 30-year compound interest")
    print("─" * 60)
    print(result2.output)


if __name__ == "__main__":
    main()
