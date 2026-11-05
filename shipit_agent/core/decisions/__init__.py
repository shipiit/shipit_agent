"""The loop's synchronous decisions, one concern per module.

:class:`~shipit_agent.core.runtime_core.RuntimeCore` is built from these
mixins. None of them awaits: they decide what to send, what to allow and what
to keep, and the loop in :mod:`shipit_agent.core.loop` decides when.
"""
