---
description: Write tools as functions, as classes, or as SDK @tool functions, and return results and errors the model can use.
---

# Custom tools

A tool is a name, a description, a JSON Schema for its arguments and a function that runs. There are three ways to write one; all three work with every model.

## From a function

The simplest. The function's name, docstring and type hints become the tool.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools import FunctionTool


def find_customer(email: str) -> str:
    """Look up a customer by email and return their plan and signup date."""
    return f"{email}: Pro plan since 2025-03-14"


agent = Agent(
    llm=build_llm_from_env(),
    tools=[FunctionTool.from_callable(find_customer, read_only=True)],
)
```

`name=` and `description=` override what is read from the function. `read_only=True` says the tool changes nothing, so it runs without asking and can run in parallel with other reads.

## As a class

A class gives you a hand-written schema, guidance for the model and full control of the result.

```python
from shipit_agent.tools.base import ToolContext, ToolOutput


class RefundTool:
    name = "refund_order"
    description = "Refund an order, in full or in part."
    prompt_instructions = "Refund only after the customer has confirmed the amount."
    read_only = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "The order to refund, e.g. A-1043."},
                        "amount": {"type": "number", "description": "Amount in dollars; omit for a full refund."},
                    },
                    "required": ["order_id"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        order_id = kwargs["order_id"]
        if not order_id.startswith("A-"):
            return ToolOutput.error(f"{order_id} is not an order id. Order ids look like A-1043.")
        amount = kwargs.get("amount")
        return ToolOutput(
            text=f"Refunded {'in full' if amount is None else f'${amount:.2f}'} on {order_id}.",
            metadata={"order_id": order_id, "amount": amount},
        )
```

| Part | What it is for |
| :- | :- |
| `name` | What the model calls. Lower snake case. |
| `description` | One line the model reads to decide whether to use the tool. `tool_search` ranks by it too. |
| `prompt_instructions` | Longer guidance on when and how to use it. |
| `read_only` | `True` if it changes nothing. Read-only tools need no approval. |
| `schema()` | The function schema. Every provider accepts this shape; adapters translate it. |
| `run(context, **kwargs)` | Does the work. `kwargs` are the model's arguments; `context` has the prompt, the session id and shared `state`. |

## Results

`ToolOutput` has three fields:

- **`text`**: the full result. Callers, traces and `result.tool_results` keep it whole.
- **`model_text`**: optionally, a shorter view for the model, such as the relevant rows of a large table. When set, the model sees it instead of `text`.
- **`metadata`**: structured data for your code. The model does not see it.

For records, `ToolOutput.from_records(rows, fields=["id", "status"], limit=20)` shows the model a page of the chosen fields with the total count, and keeps every record in `text`.

## Errors

Return `ToolOutput.error(...)` for a failure the model can fix: a bad id, a missing file, a refused request. Say what went wrong and what to try. The model sees it and adjusts in its next turn.

Raise only for failures it cannot fix. A raised exception never ends the run: the model sees `Error running tool '<name>': <message>` and carries on. Connection, timeout and OS errors are retried first, `RetryPolicy.max_tool_retries` times (once by default); `RetryPolicy.retry_on_exceptions` changes which.

## SDK tools

With the SDK API, decorate an async function with `@tool` and serve it from an in-process MCP server:

```python
from shipit_agent.sdk import AgentOptions, create_sdk_mcp_server, tool


@tool("find_customer", "Look up a customer by email", {"email": str})
async def find_customer(args):
    return {"content": [{"type": "text", "text": f"{args['email']}: Pro plan"}]}


crm = create_sdk_mcp_server("crm", tools=[find_customer])
options = AgentOptions(mcp_servers={"crm": crm}, allowed_tools=["mcp__crm__find_customer"])
```

Return `"is_error": True` in the result to report a failure the model can act on.

## Making tools easy to use

- Write the description for the model, not for people reading the code: what it does and when to use it.
- Describe every argument with an example of a valid value.
- Keep results short. Return what the model needs for its next step, and the rest in `metadata`.
- Make errors say what to do: "No file named `src/app.ts`. Did you mean `src/app.tsx`?"
