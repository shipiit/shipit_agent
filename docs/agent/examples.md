---
title: Examples
description: Complete agents to copy, one for each common job, from a read-only code explainer to a supervised support agent.
---

# Examples

Each example is a complete program. They use `build_llm_from_env()`, so they run with whichever provider your environment names; see [Configure a model](../getting-started/environment.md).

## Explain a codebase, read-only

An agent that can look but not touch: `plan` mode allows only reading.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".", permission_mode="plan")
print(agent.run("How does a request reach the database in this project? Name the files.").output)
```

## Fix a failing test, in a sandbox

Edits are allowed, and commands run in the OS sandbox, so the agent works without approvals and cannot write outside the project.

```python
import asyncio

from shipit_agent.sdk import AgentOptions, ResultMessage, query


async def main() -> None:
    options = AgentOptions(
        model="claude-sonnet-5-5",
        cwd=".",
        permission_mode="acceptEdits",
        sandbox={"enabled": True},
        max_turns=30,
        max_budget_usd=1.0,
    )
    async for message in query(prompt="Run the tests, find why they fail and fix the code.", options=options):
        if isinstance(message, ResultMessage):
            print(message.subtype, message.result)


asyncio.run(main())
```

## Review code into a structured report

```python
from pydantic import BaseModel

from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env


class Finding(BaseModel):
    file: str
    line: int
    severity: str
    problem: str
    fix: str


class Review(BaseModel):
    verdict: str
    findings: list[Finding]


agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".", permission_mode="plan")
review = agent.run("Review the changes in `git diff main` for bugs.", output_schema=Review).parsed

for f in review.findings:
    print(f"{f.severity:7} {f.file}:{f.line}  {f.problem}")
```

## Research with sources

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools import OpenURLTool, WebSearchTool

agent = Agent(
    llm=build_llm_from_env(),
    tools=[WebSearchTool(), OpenURLTool()],
    prompt="Answer from sources you have opened. Cite each claim with its URL.",
)
print(agent.run("What changed in Python 3.14's free-threaded build?").output)
```

## A support agent with your tools and a person in the loop

Read-only lookups run freely; a refund waits for a person.

```python
from shipit_agent import Agent, PermissionDecision, PermissionResult
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools import FunctionTool


def order_status(order_id: str) -> str:
    """The shipping status of an order, e.g. A-1043."""
    return f"{order_id}: delivered on 4 November"


def refund(order_id: str, amount: float) -> str:
    """Refund an amount in dollars on an order."""
    return f"Refunded ${amount:.2f} on {order_id}"


def ask_a_person(tool_name: str, arguments: dict) -> PermissionResult | None:
    if tool_name != "refund":
        return None
    answer = input(f"Refund ${arguments['amount']} on {arguments['order_id']}? [y/N] ")
    return PermissionResult(PermissionDecision.ALLOW if answer.lower() == "y" else PermissionDecision.DENY)


agent = Agent(
    llm=build_llm_from_env(),
    tools=[FunctionTool.from_callable(order_status, read_only=True), FunctionTool.from_callable(refund)],
    permission_callback=ask_a_person,
    prompt="You are a support agent for an online shop. Be brief and kind.",
)
print(agent.run("Order A-1043 arrived broken. I'd like my $40 back.").output)
```

## A chat that remembers

```python
from shipit_agent import Agent, FileSessionStore
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), session_store=FileSessionStore(".shipit/sessions"))
chat = agent.chat_session(session_id="planning")

while (line := input("you › ")) != "quit":
    print("agent ›", chat.send(line).output)
```

Run it again tomorrow with the same `session_id` and the conversation continues.

## Triage GitHub issues over MCP

```python
from shipit_agent import Agent, connect_mcp
from shipit_agent.llms import build_llm_from_env

agent = Agent(
    llm=build_llm_from_env(),
    mcps=[connect_mcp("github")],  # reads GITHUB_TOKEN
    prompt="You triage issues for shipiit/shipit_agent. Label, never close.",
)
print(agent.run("Label the issues opened this week as bug, feature or question.").output)
```

## An audit log, and a hard block on secrets

```python
from shipit_agent import Agent, AgentHooks
from shipit_agent.llms import build_llm_from_env

hooks = AgentHooks()


@hooks.on_before_tool
def audit(name: str, arguments: dict):
    print(f"[audit] {name} {arguments}")
    if ".env" in str(arguments):
        return {"decision": "deny", "reason": "Secrets are off limits."}
    return None


agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".", hooks=hooks)
agent.run("Check that the config loader handles a missing file.")
```

## A lead with specialist sub-agents

The lead hands work to sub-agents, each with its own prompt and tools. Only their summaries enter the lead's context.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(
    llm=build_llm_from_env(),
    project_root=".",
    agents={
        "reviewer": {
            "description": "Reviews a change for bugs and missing tests.",
            "prompt": "You review code. Report each problem with file:line and a fix.",
            "tools": ["read_file", "grep_files", "glob_files"],
        },
        "tester": {
            "description": "Runs the test suite and reports failures.",
            "prompt": "Run the tests and report each failure with its cause.",
            "tools": ["bash", "read_file"],
        },
    },
)
print(agent.run("Add input validation to src/api/users.py, then have it reviewed and tested.").output)
```

## Survive a flaky provider

Retries for transient errors, then a fallback model.

```python
from shipit_agent import Agent, RetryPolicy
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(
    llm=build_llm_from_env("anthropic"),
    fallback_model=build_llm_from_env("openai"),
    retry_policy=RetryPolicy(max_llm_retries=3, llm_retry_max_delay=20.0),
)
```

## More

- [Deep agent recipes](../guides/deep-agents.md): goal-driven, reflective and supervised agents.
- [RAG with an agent](../rag/with-agent.md): answers grounded in your documents, with citations.
- The [`examples/`](https://github.com/shipiit/shipit_agent/tree/main/examples) folder in the repository: runnable scripts and notebooks.
