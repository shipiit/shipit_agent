"""Self-healing tool calls — promote text-emitted calls to structured ones.

Small open-weight models frequently write a tool call into their TEXT
instead of the structured tool-call field::

    <tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>
    ```json
    {"name": "read_file", "arguments": {"path": "app.py"}}
    ```

The runtime heals these on the RESPONSE side only, under strict invariants
(modeled on the behavior of production healing layers):

- only names in the agent's DECLARED tool set are promoted;
- promotion removes exactly the promoted span — every other byte of the
  model's text is preserved;
- unparseable or undeclared blocks are left as plain text, never dropped;
- healing never issues extra generation.

Disable per-agent with ``Agent(heal_tool_calls=False)``.
"""

from __future__ import annotations

from .arguments import (
    _arguments_fit_schema,
    call_carries_nothing,
    repair_argument_names,
    schemas_from_tools,
)
from .heal import heal_tool_calls, merge_split_calls

__all__ = [
    "_arguments_fit_schema",
    "call_carries_nothing",
    "heal_tool_calls",
    "merge_split_calls",
    "repair_argument_names",
    "schemas_from_tools",
]
