"""The decisions the agent loop makes that never need to await.

:class:`RuntimeCore` is built from one mixin per concern (tool calls, step
messages, deferral, guardrails, permissions, response checks, usage, context
fit, shared tool state, wrap-up). The loop itself, in
:mod:`shipit_agent.core.async_runtime`, decides *when*; these decide *what*:
what to do with a response, when to compact, when to latch lockdown, what
state a tool can see.

A method belongs here if it does not need to await anything. The helper
names re-exported below lived in this module before the split.
"""

from __future__ import annotations

import threading
from typing import Any

from shipit_agent.core.decisions.artifact_paths import (
    _ARTIFACT_KINDS,
    _PATH_KEYS,
    _PATH_LIST_KEYS,
    _artifact_kind,
    _declared_paths,
)
from shipit_agent.core.decisions.call_keys import (
    _REPEAT_MIN_CHARS,
    WITHHELD_TOOLS_KEY,
    _arguments_key,
)
from shipit_agent.core.decisions.context_fit import ContextFitMixin
from shipit_agent.core.decisions.cost_budget import CostBudgetMixin
from shipit_agent.core.decisions.guardrail_checks import GuardrailChecksMixin
from shipit_agent.core.decisions.permission_gate import PermissionGateMixin
from shipit_agent.core.decisions.prior_outputs import (
    _EVICT_MIN_CHARS,
    _evicted_notice,
    attach_reminder,
    evict_prior_tool_outputs,
)
from shipit_agent.core.decisions.repeat_guard import RepeatGuardMixin
from shipit_agent.core.decisions.requested_tools import RequestedToolsMixin
from shipit_agent.core.decisions.response_checks import ResponseChecksMixin
from shipit_agent.core.decisions.run_wrap_up import RunWrapUpMixin
from shipit_agent.core.decisions.shared_tool_state import SharedToolStateMixin
from shipit_agent.core.decisions.step_messages import StepMessagesMixin
from shipit_agent.core.decisions.tool_calls import ToolCallsMixin
from shipit_agent.core.decisions.tool_deferral import ToolDeferralMixin
from shipit_agent.core.decisions.usage_budget import UsageBudgetMixin
from shipit_agent.safety.action_detection import is_malformed_action_attempt

__all__ = [
    "RuntimeCore",
    "is_malformed_action_attempt",
    "_ARTIFACT_KINDS",
    "_PATH_KEYS",
    "_PATH_LIST_KEYS",
    "_artifact_kind",
    "_declared_paths",
    "_EVICT_MIN_CHARS",
    "attach_reminder",
    "_evicted_notice",
    "evict_prior_tool_outputs",
    "_REPEAT_MIN_CHARS",
    "WITHHELD_TOOLS_KEY",
    "_arguments_key",
]


class RuntimeCore(
    RequestedToolsMixin,
    ToolCallsMixin,
    RepeatGuardMixin,
    StepMessagesMixin,
    ToolDeferralMixin,
    GuardrailChecksMixin,
    PermissionGateMixin,
    ResponseChecksMixin,
    UsageBudgetMixin,
    CostBudgetMixin,
    ContextFitMixin,
    SharedToolStateMixin,
    RunWrapUpMixin,
):
    """Shared, synchronous decisions for both agent loops.

    Expects the host to provide: ``llm``, ``prompt``, ``metadata``, ``mcps``,
    ``permissions``, ``guardrails``, ``hooks``, ``lockdown``, ``approvals``,
    ``heal_tool_calls``, ``context_window_tokens``, ``credential_store``,
    ``memory_store``, and an ``emit(state, type, message, **payload)``.
    """

    def _init_core(self, **options: Any) -> None:
        """Initialise the shared fields. Call from the host's ``__init__``."""
        from shipit_agent.approvals import coerce_queue
        from shipit_agent.safety.lockdown import coerce_lockdown

        self.guardrails = options.get("guardrails")
        self.lockdown = coerce_lockdown(options.get("lockdown"))
        self.approvals = coerce_queue(options.get("approvals"))
        self.heal_tool_calls = bool(options.get("heal_tool_calls", True))
        self.code_mode = bool(options.get("code_mode", False))
        self.context_window_tokens = int(options.get("context_window_tokens", 0) or 0)
        self._session_runtime_state = options.get("session_runtime_state")
        if self._session_runtime_state is None:
            self._session_runtime_state = {}
        # The fixed prompt prefix (system prompt + tool schemas) is sent on
        # every call but lives outside ``messages``. Counted toward the
        # compaction trigger so it does not fire ~a-prefix's-worth late. 0 keeps
        # the pre-existing messages-only behaviour.
        self._fixed_prefix_tokens = int(options.get("fixed_prefix_tokens", 0) or 0)
        self._configured_fixed_prefix_tokens = self._fixed_prefix_tokens
        # Learns the per-model gap between our chars/4 estimate and the
        # provider's real ``prompt_tokens`` (fed at each completion) so the
        # trigger uses a calibrated number. Always present; harmless until it
        # has enough samples, and clamped so it can only ever compact earlier.
        from shipit_agent.context.token_calibration import TokenCalibrator

        self.token_calibrator = self._session_runtime_state.setdefault(
            "token_calibrator", TokenCalibrator()
        )
        self.max_tool_output_chars = int(options.get("max_tool_output_chars", 0) or 0)
        self.max_tool_output_group_chars = int(
            options.get("max_tool_output_group_chars", 0) or 0
        )
        self.tool_output_dir = str(options.get("tool_output_dir") or "")
        self.reminder = options.get("reminder") or None
        # Verify-on-stop: refuse to finish a turn that edited code without fresh
        # passing tests (evidence-gated coding). Off by default — it changes the
        # loop's stop behaviour, so a caller opts in.
        self.verify_before_stop = bool(options.get("verify_before_stop", False))
        self.evict_prior_tool_outputs = bool(
            options.get("evict_prior_tool_outputs", True)
        )
        # False | True | iterable of names — see shipit_agent.deferral.
        self.deferred_tools = options.get("deferred_tools", "auto")

        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        self._total_uncached_input = 0
        self._total_context_input = 0
        self._request_estimates = {"system": 0, "conversation": 0, "tool_results": 0, "schemas": 0}
        self._purpose_usage = {"main": 0, "compaction": 0}
        # Tokens a routed step spent on a call it then threw away (StepRouter
        # escalation): real spend, so budgets and totals count it.
        self._discarded_tokens = 0
        # Per-model token buckets, so a run served by several models (a
        # StepRouter) is priced at each model's own rate.
        self._usage_by_model: dict[str, dict[str, int]] = {}
        self._schema_prefix = ""
        self._prefix_changes = 0
        self._cache_counters_reported = False
        self._usage_reports = 0
        self._complete_usage_reports = 0
        self._completed_model_calls = 0
        # Time spent waiting on the model, retries included, backoff not.
        self._api_seconds = 0.0
        self._fallbacks_used = 0
        self._permission_denials: list[dict[str, Any]] = []
        # A call a hook deferred; the run pauses after its step (see paused_calls).
        self._deferred_tool_use: dict[str, Any] | None = None
        self._cancel_event = threading.Event()
        self._guarded_tool_calls = 0
        self._nudges_used = 0
        self._last_nudged_text = ""
        # Text-only recovery is offered once a turn; after it, the reply stands.
        self._text_recovery_used = False
        self._requested_tool_nudges: set[str] = set()
        self._compactor_instance: Any = self._session_runtime_state.get("compactor")
        self.connections: Any = None
























    #: How many image messages a request keeps. Screenshots age fast — the
    #: model acts on the newest one; older ones are pure input cost.
    MAX_VISION_MESSAGES = 3









    def cancel(self) -> None:
        """Request cancellation (thread-safe); the loop stops at its next checkpoint."""
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

















    # Reprompt-on-failure, in the spirit of production tool-runners: name why
    # the attempt did not count (the tool name or its arguments were mistyped
    # or written as prose, so nothing ran) and tell the model exactly how to
    # recover. Kept as a cross-provider user message rather than a synthetic
    # tool-response: shipit's Message model does not carry a tool_call_id to
    # pair a fabricated failure result against, and an unpaired tool message is
    # rejected by strict providers (Bedrock-Anthropic). The wording gives the
    # same self-correction signal without that fragility.
    NUDGE_TEXT = (
        "You attempted a tool call, but it was not emitted as a structured "
        "call — the tool name or its arguments were likely mistyped or written "
        "as prose, so nothing ran. Re-issue it now as a real structured call "
        "with the exact tool name and correctly-typed arguments, or, if no tool "
        "is needed, give your final answer directly. Do not describe the call "
        "in text."
    )

    #: How many times a turn under ``require_tool_call`` (force-any-tool) may be
    #: re-prompted to emit the mandatory call before the runtime gives up and
    #: lets the model answer from what it has. Without a cap the forced-tool
    #: retry re-fires every iteration to ``max_iterations`` — the visible
    #: "Retrying required tool use" loop. Two attempts is enough for a model
    #: that merely stumbled; a model that will not call it never will.
    MAX_FORCE_ANY_RETRIES = 2

    #: How many times stop hooks may send one run back to work. A hook that
    #: never relents must not turn every answer into ``max_iterations`` steps.
    MAX_STOP_CONTINUATIONS = 3


























