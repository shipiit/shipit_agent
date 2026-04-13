"""Custom exceptions for ShipCrew orchestration.

Each error type maps to a specific failure mode in the DAG-based
crew execution pipeline, making it easy to catch and handle
individual failure categories.
"""

from __future__ import annotations


class ShipCrewError(Exception):
    """Base exception for all ShipCrew-related errors."""


class CyclicDependencyError(ShipCrewError):
    """Raised when the task DAG contains a cycle.

    A cycle means two or more tasks depend on each other (directly or
    transitively), making it impossible to determine a valid execution
    order.
    """


class MissingAgentError(ShipCrewError):
    """Raised when a task references an agent that is not registered in the crew."""


class TaskTimeoutError(ShipCrewError):
    """Raised when a task exceeds its configured ``timeout_seconds``."""
