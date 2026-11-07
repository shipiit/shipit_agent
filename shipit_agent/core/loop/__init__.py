"""The agent loop, one phase or concern per module.

:class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime` mixes these in.
A turn runs :mod:`.turn_setup`, then :mod:`.turn_steps` (each step ends in
:mod:`.answer_step` or :mod:`.tool_step`, which runs calls through
:mod:`.tool_exec`), then :mod:`.turn_finish`. :class:`.turn.Turn` carries the
state between them.
"""
