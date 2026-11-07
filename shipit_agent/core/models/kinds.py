"""The roles a message can have and the types an event can have."""

from __future__ import annotations

from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


EventType = Literal[
    "run_started",
    "iteration_started",
    "reasoning_started",
    "reasoning_delta",
    "reasoning_completed",
    "text_delta",
    "assistant_message",
    "tool_group_started",
    "tool_called",
    "tool_input_delta",
    "tool_output_delta",
    "tool_completed",
    "tool_failed",
    "tool_denied",
    "tool_deferred",
    "tool_arguments_rejected",
    "tool_group_completed",
    "skill_catalog_ready",
    "skill_loaded",
    "mcp_attached",
    "tools_discovered",
    "tools_rebound",
    "task_started",
    "task_notification",
    "subagent_started",
    "subagent_event",
    "subagent_completed",
    "context_compaction_started",
    "context_compacted",
    "approval_required",
    "checkpoint_saved",
    "usage_tick",
    "llm_retry",
    "final_answer",
    "run_summary",
    "run_completed",
    "run_failed",
    "run_cancelled",
]
