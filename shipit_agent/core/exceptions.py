"""Exceptions raised by shipit-agent itself.
"""

class ShipitAgentError(Exception):
    """Base package exception."""


class DuplicateToolError(ShipitAgentError):
    """Raised when two tools share the same public name."""
