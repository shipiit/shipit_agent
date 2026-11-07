"""The agent loop: every phase of a turn, as one class the runtimes build on.

Each mixin owns one part of a turn (setup, history, steps, tool calls, the
finish). Their order is the method resolution order the runtime relies on.
"""

from __future__ import annotations

from shipit_agent.core.loop.answer_step import AnswerStepMixin
from shipit_agent.core.loop.code_mode import CodeModeMixin
from shipit_agent.core.loop.event_stream import EventStreamMixin
from shipit_agent.core.loop.model_call import ModelCallMixin
from shipit_agent.core.loop.paused_calls import PausedCallMixin
from shipit_agent.core.loop.planning import PlanningMixin
from shipit_agent.core.loop.step_narration import StepNarrationMixin
from shipit_agent.core.loop.task_watch import TaskWatchMixin
from shipit_agent.core.loop.tool_attempts import ToolAttemptsMixin
from shipit_agent.core.loop.tool_denial import ToolDenialMixin
from shipit_agent.core.loop.tool_exec import ToolExecutionMixin
from shipit_agent.core.loop.tool_outcome import ToolOutcomeMixin
from shipit_agent.core.loop.tool_step import ToolStepMixin
from shipit_agent.core.loop.turn_finish import TurnFinishMixin
from shipit_agent.core.loop.turn_history import TurnHistoryMixin
from shipit_agent.core.loop.turn_setup import TurnSetupMixin
from shipit_agent.core.loop.turn_steps import TurnStepsMixin
from shipit_agent.core.loop.turn_tools import TurnToolsMixin


class AgentLoop(
    EventStreamMixin,
    PlanningMixin,
    ModelCallMixin,
    StepNarrationMixin,
    ToolExecutionMixin,
    ToolDenialMixin,
    TaskWatchMixin,
    PausedCallMixin,
    ToolAttemptsMixin,
    ToolOutcomeMixin,
    TurnSetupMixin,
    TurnHistoryMixin,
    TurnToolsMixin,
    TurnStepsMixin,
    AnswerStepMixin,
    ToolStepMixin,
    TurnFinishMixin,
    CodeModeMixin,
):
    """Every phase of a turn; :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime` adds the state."""
