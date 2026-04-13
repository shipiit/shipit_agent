"""ShipCrew — multi-agent crew orchestration with DAG-based task execution.

Provides a high-level API for composing specialised agents into
collaborative workflows with automatic data flow between tasks.

Public API::

    from shipit_agent.deep.ship_crew import (
        ShipCrew,
        ShipAgent,
        ShipTask,
        ShipCrewResult,
        create_ship_crew,
    )
"""

from .agent import ShipAgent
from .crew import ShipCrew, create_ship_crew
from .errors import (
    CyclicDependencyError,
    MissingAgentError,
    ShipCrewError,
    TaskTimeoutError,
)
from .result import ShipCrewResult
from .task import ShipTask

__all__ = [
    "CyclicDependencyError",
    "MissingAgentError",
    "ShipAgent",
    "ShipCrew",
    "ShipCrewError",
    "ShipCrewResult",
    "ShipTask",
    "TaskTimeoutError",
    "create_ship_crew",
]
