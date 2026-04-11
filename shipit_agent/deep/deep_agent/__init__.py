"""Deep Agent — power-user ``create_deep_agent`` factory.

Inspired by LangChain's ``deepagents`` package, but more powerful: see
the comparison table in :mod:`shipit_agent.deep.deep_agent.factory`.

Public surface:

- :class:`DeepAgent`              — the factory class
- :func:`create_deep_agent`       — LangChain-style functional helper
- :data:`DEEP_AGENT_PROMPT`       — the opinionated system prompt
"""

from .delegation import AgentDelegationTool, build_delegation_tool
from .factory import DeepAgent, create_deep_agent
from .prompt import DEEP_AGENT_PROMPT

__all__ = [
    "AgentDelegationTool",
    "DEEP_AGENT_PROMPT",
    "DeepAgent",
    "build_delegation_tool",
    "create_deep_agent",
]
