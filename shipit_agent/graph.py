"""The run loop, as an explicit graph that yields everything as it happens.

A generator rather than a function that returns at the end: an agent run is a
sequence of observable moments, and the caller — a CLI, an SSE endpoint, a
notebook — wants each one as it occurs, not a transcript afterwards. Token
deltas, streamed tool arguments, live tool output, skill loads, sub-agent
activity and compaction all arrive as :class:`AgentEvent` values on one channel.
:class:`~shipit_agent.models.AgentResult` is assembled from the same stream, so
the streaming and non-streaming paths cannot drift.

The loop is small on purpose. Each iteration is:

    plan the prompt → call the model → stream text → run tool calls → repeat

and everything that varies by provider has already been resolved before the loop
starts: parameters sanitised, schemas prepared for the right dialect, images
converted, reasoning history applied. The loop itself contains no provider
branches, which is what lets one implementation serve every model.

Three decisions in here are about not burning tokens:

* **The prefix is built once** and reused verbatim. Implicit prompt caching keys
  on a byte-stable prefix, and rebuilding it per iteration silently loses every
  cache hit.
* **Skills load on demand.** The catalog costs about ten tokens per skill; a
  body is paid only when the model asks for one, at whatever iteration it
  discovers it needs it.
* **Tool output is bounded before it enters history**, because a message list is
  cumulative — a large result is not paid once, it is re-sent on every
  subsequent turn.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

from shipit_agent.llms.capabilities import ModelCapabilities, capabilities_for
from shipit_agent.llms.parameters import ResolvedParameters, resolve_parameters
from shipit_agent.discovery import DiscoveryState, ToolSearchTool, filter_schemas
from shipit_agent.llms.schema_prep import prepare_tool_schema
from shipit_agent.llms.wire import apply_reasoning_policy
from shipit_agent.models import (
    AgentEvent,
    AgentResult,
    Message,
    ToolCall,
    ToolResult,
    pair_calls_and_results,
)
from shipit_agent.prefix import PromptPrefix, build_prefix
from shipit_agent.skills.catalog import LoadSkillTool, SkillSession, build_catalog
from shipit_agent.toolkit.contracts import run_tool_safely
from shipit_agent.usage import Purpose, ServiceTier, TierPolicy, UsageLedger

logger = logging.getLogger(__name__)

__all__ = ["RunSpec", "AgentGraph", "StopReason"]


class _LLM(Protocol):
    def complete(self, **kwargs: Any) -> Any: ...


class _Tool(Protocol):
    name: str

    def schema(self) -> dict[str, Any]: ...
    def run(self, context: Any, **kwargs: Any) -> Any: ...


class StopReason(str):
    """Why the loop ended. A string subclass so it serialises transparently."""

    FINISHED = "finished"
    MAX_ITERATIONS = "max_iterations"
    CANCELLED = "cancelled"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"


@dataclass
class RunSpec:
    """Everything one run needs, resolved before the loop starts.

    Assembling this eagerly is deliberate: by the time the loop runs there is
    nothing left to decide that depends on the provider, so the loop has no
    provider branches and every model takes the same path.
    """

    llm: Any
    model: str
    system_prompt: str = "You are a capable, careful assistant."
    tools: Sequence[Any] = ()
    skills: Sequence[Any] = ()
    always_apply_skills: Sequence[Any] = ()
    rules: str = ""
    #: An :class:`~shipit_agent.mcp_bridge.MCPBridge`, already attached. Its
    #: instructions join the prefix and its tools connect on first use.
    mcp: Any = None
    mcp_instructions: Mapping[str, str] = field(default_factory=dict)
    #: Tool names held behind ``tool_search`` rather than bound up front.
    deferred_tools: Sequence[str] = ()
    model_parameters: Mapping[str, Any] = field(default_factory=dict)
    max_iterations: int = 12
    max_tool_output_chars: int = 16_000
    tier_policy: TierPolicy | None = None
    ledger: UsageLedger | None = None
    should_cancel: Callable[[], bool] | None = None
    approve: Callable[[ToolCall], bool] | None = None
    #: Compacts history when it grows; returns the replacement message list.
    compact: Callable[[list[Message]], list[Message] | None] | None = None

    def capabilities(self) -> ModelCapabilities:
        return capabilities_for(self.model)


def _event(kind: str, message: str = "", **payload: Any) -> AgentEvent:
    return AgentEvent(type=kind, message=message, payload=payload)  # type: ignore[arg-type]


class AgentGraph:
    """One run: prompt in, :class:`AgentEvent` stream out.

    Constructed per run rather than per agent, because a run owns mutable state
    — the skill session, the ledger, the message list — that must not leak into
    the next one.
    """

    def __init__(self, spec: RunSpec) -> None:
        self.spec = spec
        self.caps = spec.capabilities()
        #: Resolved once: wire params, host params, and a record of every
        #: decision. `parameters.explain()` is what turns a provider 400 into a
        #: one-line answer.
        self.parameters: ResolvedParameters = resolve_parameters(
            spec.model, spec.model_parameters
        )
        self.ledger = spec.ledger or UsageLedger()
        self.messages: list[Message] = []
        self.tool_results: list[ToolResult] = []
        self.events: list[AgentEvent] = []
        self.stop_reason: str = StopReason.FINISHED
        self.pending_call: ToolCall | None = None
        self._discovery_dirty = False
        self._prefix_rebuilds = 0

        self.max_iterations = int(
            self.parameters.host_value("max_iterations", spec.max_iterations)
        )
        self.max_tool_output_chars = int(
            self.parameters.host_value(
                "max_tool_output_chars", spec.max_tool_output_chars
            )
        )
        self._tools: dict[str, Any] = {t.name: t for t in spec.tools}
        self.mcp_instructions: dict[str, Any] = dict(spec.mcp_instructions)
        self._install_mcp()
        self.discovery = self._install_discovery()
        self.skill_session = SkillSession(base_tools=frozenset(self._tools))
        self._install_skills()
        self.prefix: PromptPrefix = self._build_prefix()
        self._prefix_fingerprint = self.prefix.fingerprint()

    # -- setup -------------------------------------------------------------

    def _install_mcp(self) -> None:
        """Fold an attached bridge's tools and instructions into the run.

        Tools connect on first call, so attaching twenty servers costs twenty
        cache reads rather than twenty subprocesses. Server instructions join
        the prefix — the MCP spec defines that field for the server to tell the
        model how to use it, and dropping it makes the model learn those rules
        by failing.
        """
        bridge = self.spec.mcp
        if bridge is None:
            return
        for tool in bridge.tools(self._connect_mcp):
            self._tools.setdefault(tool.name, tool)
        self.mcp_instructions.update(bridge.instructions())

    def _connect_mcp(self, server: str) -> Any:
        """Resolve a live connection for *server*. Overridden by the host."""
        connect = getattr(self.spec.mcp, "connect", None)
        if callable(connect):
            return connect(server)
        raise RuntimeError(
            f"No connection factory for MCP server {server!r}. Pass one on the "
            "bridge as `connect(server_name)`."
        )

    def _install_discovery(self) -> DiscoveryState:
        """Hold the expensive tail behind ``tool_search``.

        Every bound tool costs its whole schema on every turn. A run that will
        touch three of two hundred tools should not pay for a hundred and
        ninety-seven, and a search round-trip is far cheaper than that tax.
        """
        state = DiscoveryState()
        bridge = self.spec.mcp
        if bridge is not None:
            state = DiscoveryState.from_descriptors(bridge.descriptors())
        for name in self.spec.deferred_tools:
            tool = self._tools.get(name)
            if tool is not None:
                state.deferred.setdefault(name, getattr(tool, "description", ""))

        # Registered whenever anything could be deferred — including when this
        # run happens to fit inside the eager budget. A model that reaches for
        # tool_search and is told no such tool exists concludes the capability
        # is absent, which is worse than an empty search result.
        if state.deferred or self.spec.mcp is not None:
            schemas = {
                name: tool.schema()
                for name, tool in self._tools.items()
                if name in state.deferred
            }
            search = ToolSearchTool(state, schemas=schemas)
            self._tools[search.name] = search
        return state

    def _install_skills(self) -> None:
        """Prime always-apply skills and expose ``load_skill`` for the rest."""
        for skill in self.spec.always_apply_skills:
            self.skill_session.prime(
                skill, trigger="always_apply", available_tools=self._tools
            )
        if self.spec.skills:
            registry = {s.id: s for s in self.spec.skills}
            loader = LoadSkillTool(
                registry, self.skill_session, available_tools=self._tools
            )
            self._tools[loader.name] = loader

    def _build_prefix(self) -> PromptPrefix:
        """Built once. Rebuilding per iteration is how cache hits are lost."""
        dialect = self.caps.schema_dialect
        schemas = filter_schemas(
            self.discovery,
            [
                prepare_tool_schema(tool.schema(), dialect=dialect)
                for tool in self._tools.values()
            ],
        )
        return build_prefix(
            system_prompt=self.spec.system_prompt,
            rules=self.spec.rules,
            mcp_instructions=self.mcp_instructions,
            skill_catalog=build_catalog(self.spec.skills),
            tool_definitions=schemas,
        )

    def _request_parameters(self, purpose: Purpose) -> dict[str, Any]:
        """Wire parameters only, adapted to this family and tagged with a tier.

        Host parameters (``max_context_tokens``, ``file_token_limit``) are
        resolved once in the constructor and never reach the provider — sending
        one is a 400 on a field the caller never aimed at the model.
        """
        wire = dict(self.parameters.wire)
        policy = self.spec.tier_policy
        if policy is not None:
            wire |= policy.as_request_param(
                purpose, supported=self.caps.supports_service_tier
            )
        return wire

    # -- the loop ----------------------------------------------------------

    def run(self, prompt: str) -> Iterator[AgentEvent]:
        """Execute the run, yielding every moment as it happens."""
        started = time.perf_counter()
        self.messages.append(Message(role="user", content=prompt))

        yield self._emit(
            _event(
                "run_started",
                model=self.spec.model,
                tools=sorted(self._tools),
                prefix_fingerprint=self._prefix_fingerprint,
                primed_skills=sorted(self.skill_session.primed),
            )
        )

        if self.spec.mcp is not None:
            for event in self.spec.mcp.events():
                yield self._emit(event)

        answer = ""
        try:
            for iteration in range(1, self.max_iterations + 1):
                if self._cancelled():
                    self.stop_reason = StopReason.CANCELLED
                    yield self._emit(_event("run_cancelled", "Cancelled."))
                    break

                yield self._emit(_event("iteration_started", iteration=iteration))
                yield from self._maybe_compact()

                yield from self._rebind_if_discovered()
                text, calls = yield from self._call_model(iteration)

                if not calls:
                    answer = text
                    # The answer belongs in history: a resumed run, a follow-up
                    # turn and `result()` all read the conversation, and an
                    # answer that lives only in an event is invisible to them.
                    self.messages.append(Message(role="assistant", content=text))
                    yield self._emit(_event("final_answer", text, text=text))
                    self.stop_reason = StopReason.FINISHED
                    break

                self.messages.append(
                    Message(role="assistant", content=text, tool_calls=calls)
                )
                stopped = yield from self._run_tool_batch(calls, iteration)
                if stopped:
                    break
            else:
                self.stop_reason = StopReason.MAX_ITERATIONS
                answer = self._last_assistant_text()
        except Exception as error:  # noqa: BLE001 — the run's outer boundary
            logger.exception("Run failed")
            self.stop_reason = StopReason.FAILED
            yield self._emit(_event("run_failed", str(error), error=str(error)))

        summary = self.ledger.summary()
        summary["duration_seconds"] = round(time.perf_counter() - started, 3)
        summary["stop_reason"] = self.stop_reason
        # Two different things, and conflating them makes the useful one
        # unreadable: the prefix legitimately changes when a search widens the
        # tool set, and that is not the drift worth alarming about. Unexplained
        # movement — a rules block rebuilt per call, a tool set iterating in a
        # new order — is.
        moved = self.prefix.fingerprint() != self._prefix_fingerprint
        summary["prefix_rebuilds"] = self._prefix_rebuilds
        summary["prefix_stable"] = not moved or self._prefix_rebuilds > 0
        summary["prefix_drifted_unexpectedly"] = moved and self._prefix_rebuilds == 0
        summary["parameters"] = self.parameters.explain()
        yield self._emit(_event("run_summary", **summary))
        yield self._emit(_event("run_completed", answer, text=answer))

    # -- model call --------------------------------------------------------

    def _call_model(self, iteration: int) -> Iterator[AgentEvent]:
        """One completion, streaming text as it arrives.

        Returns ``(text, tool_calls)`` through the generator's return value, so
        the caller stays a plain ``yield from``.
        """
        chunks: list[str] = []

        def on_text(delta: str) -> None:
            if delta:
                chunks.append(delta)

        def on_tool_input(call_id: str, name: str, delta: str) -> None:
            pending.append((call_id, name, delta))

        pending: list[tuple[str, str, str]] = []

        history = apply_reasoning_policy(self.messages, caps=self.caps)
        response = self.spec.llm.complete(
            messages=list(history),
            tools=self.prefix.tools,
            system_prompt=self.prefix.system_text,
            text_delta_callback=on_text,
            tool_input_callback=on_tool_input,
            **self._request_parameters(Purpose.MAIN),
        )

        for delta in chunks:
            yield self._emit(_event("text_delta", delta, chunk=delta, iteration=iteration))
        for call_id, name, delta in pending:
            yield self._emit(
                _event("tool_input_delta", delta, tool=name, tool_call_id=call_id, chunk=delta)
            )

        reasoning = getattr(response, "reasoning_content", None)
        if reasoning:
            yield self._emit(_event("reasoning_delta", reasoning, chunk=reasoning))

        self._record_usage(response)

        text = getattr(response, "content", "") or "".join(chunks)
        calls = [
            call.ensure_id()
            for call in getattr(response, "tool_calls", None) or []
        ]
        for index, call in enumerate(calls):
            call.index = index
        return text, calls

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None) or {}
        if not usage:
            return
        record = self.ledger.sink(Purpose.MAIN, self.spec.model)
        record(
            usage,
            cache_included_in_input=self.caps.prompt_cache_mode != "none",
            tier=(
                self.spec.tier_policy.tier_for(Purpose.MAIN)
                if self.spec.tier_policy
                else ServiceTier.STANDARD
            ),
        )

    # -- tools -------------------------------------------------------------

    def _run_tool_batch(self, calls: list[ToolCall], iteration: int) -> Iterator[AgentEvent]:
        """Execute one batch. Returns True through the generator if the run stops."""
        yield self._emit(
            _event("tool_group_started", tools=[c.name for c in calls], iteration=iteration)
        )

        for call in calls:
            if self._cancelled():
                self.stop_reason = StopReason.CANCELLED
                yield self._emit(_event("run_cancelled", "Cancelled."))
                return True

            yield self._emit(
                _event(
                    "tool_called",
                    tool=call.name,
                    tool_call_id=call.id,
                    arguments=dict(call.arguments),
                    iteration=iteration,
                )
            )

            if self.spec.approve is not None and not self.spec.approve(call):
                self.pending_call = call
                self.stop_reason = StopReason.APPROVAL_REQUIRED
                yield self._emit(
                    _event("approval_required", tool=call.name, tool_call_id=call.id)
                )
                return True

            result = yield from self._execute(call)
            self.tool_results.append(result)
            self.messages.append(Message.from_tool_result(result))

            yield self._emit(
                _event(
                    "tool_failed" if result.is_error else "tool_completed",
                    result.output[:200],
                    tool=call.name,
                    tool_call_id=call.id,
                    duration_ms=result.duration_ms,
                    truncated=result.truncated,
                )
            )
            if call.name == "tool_search" and not result.is_error:
                self._discovery_dirty = True
                yield self._emit(
                    _event(
                        "tools_discovered",
                        tool_call_id=call.id,
                        tools=result.metadata.get("tools", []),
                    )
                )
            if call.name == "load_skill" and not result.is_error:
                yield self._emit(
                    _event(
                        "skill_loaded",
                        tool_call_id=call.id,
                        skill_id=result.metadata.get("skill_id", ""),
                        unlocked_tools=result.metadata.get("unlocked_tools", []),
                    )
                )

        yield self._emit(_event("tool_group_completed", iteration=iteration))
        return False

    def _execute(self, call: ToolCall) -> Iterator[AgentEvent]:
        """Run one tool, streaming its output live if it produces chunks."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                name=call.name,
                output=(
                    f"No tool named {call.name!r}. Available: "
                    f"{', '.join(sorted(self._tools))}."
                ),
                tool_call_id=call.id,
                is_error=True,
            )

        if not self.discovery.is_available(call.name):
            return ToolResult(
                name=call.name,
                output=(
                    f"{call.name} is not loaded. Use tool_search to find and "
                    "load it first."
                ),
                tool_call_id=call.id,
                is_error=True,
            )

        always_allowed = {"load_skill", "tool_search"}
        if (
            call.name not in self.skill_session.allowed_tools
            and call.name not in always_allowed
            and call.name not in self.discovery.discovered
        ):
            return ToolResult(
                name=call.name,
                output=(
                    f"{call.name} is not available yet. A skill that provides it "
                    "may need loading first."
                ),
                tool_call_id=call.id,
                is_error=True,
            )

        streamed: list[str] = []
        carried: dict[str, Any] = {}

        def execute() -> str:
            output = tool.run(self._tool_context(call), **call.arguments)
            if isinstance(output, str):
                return output
            # Captured before the text, because a tool that returns an error
            # says so in its metadata and the runtime must not read that as a
            # successful result.
            extra = getattr(output, "metadata", None)
            if isinstance(extra, dict):
                carried.update(extra)
            text = getattr(output, "text", None)
            if isinstance(text, str):
                return text
            # An iterable of chunks: collect for the result, keep each piece so
            # it can be published live rather than only at completion.
            if isinstance(output, Iterable):
                for chunk in output:
                    piece = getattr(chunk, "text", chunk)
                    streamed.append(str(piece))
                return "".join(streamed)
            return str(output)

        result = run_tool_safely(
            call,
            execute,
            output_limit=self.max_tool_output_chars,
            recovery_hint="Re-run with a narrower query to see the rest.",
            metadata=carried,
        )

        for piece in streamed or ([result.output] if result.output else []):
            if piece:
                yield self._emit(
                    _event(
                        "tool_output_delta",
                        piece,
                        chunk=piece,
                        tool=call.name,
                        tool_call_id=call.id,
                    )
                )
        return result

    def _tool_context(self, call: ToolCall) -> Any:
        from shipit_agent.tools_compat import ToolOutput  # noqa: F401 — shim import

        return type(
            "RunContext",
            (),
            {
                "prompt": self.messages[0].text if self.messages else "",
                "system_prompt": self.prefix.system_text,
                "metadata": {"tool_call_id": call.id},
                "state": {"skills": self.skill_session},
                "session_id": None,
            },
        )()

    # -- housekeeping ------------------------------------------------------

    def _rebind_if_discovered(self) -> Iterator[AgentEvent]:
        """Rebuild the tool binding when ``tool_search`` widened it.

        Only when it actually changed: the prefix must stay byte-stable for
        implicit caching, so it is rebuilt on a real capability change and never
        speculatively.
        """
        if not self._discovery_dirty:
            return
        self._discovery_dirty = False
        self.prefix = self._build_prefix()
        self._prefix_rebuilds += 1
        yield self._emit(
            _event(
                "tools_rebound",
                discovered=sorted(self.discovery.discovered),
                bound=len(self.prefix.tool_definitions),
            )
        )

    def _maybe_compact(self) -> Iterator[AgentEvent]:
        if self.spec.compact is None:
            return
        replacement = self.spec.compact(self.messages)
        if replacement is None or replacement is self.messages:
            return
        before, after = len(self.messages), len(replacement)
        self.messages = list(replacement)
        yield self._emit(
            _event("context_compacted", messages_before=before, messages_after=after)
        )

    def _cancelled(self) -> bool:
        return bool(self.spec.should_cancel and self.spec.should_cancel())

    def _last_assistant_text(self) -> str:
        for message in reversed(self.messages):
            if message.role == "assistant" and message.text:
                return message.text
        return ""

    def _emit(self, event: AgentEvent) -> AgentEvent:
        self.events.append(event)
        return event

    # -- result ------------------------------------------------------------

    def result(self, output: str = "") -> AgentResult:
        """Assemble the run's result from the same state the stream reported."""
        ok, problems = pair_calls_and_results(self.messages)
        if not ok:
            # Never fatal, always visible: unpaired calls are the exact defect
            # that request-rewriting used to hide, so they belong in the record.
            logger.warning("Tool call pairing problems: %s", "; ".join(problems))
        return AgentResult(
            output=output or self._last_assistant_text(),
            messages=list(self.messages),
            events=list(self.events),
            tool_results=list(self.tool_results),
            metadata={
                "usage": self.ledger.totals(),
                "by_purpose": self.ledger.by_purpose(),
                "stop_reason": self.stop_reason,
                "primed_skills": sorted(self.skill_session.primed),
                "discovered_tools": sorted(self.discovery.discovered),
                "pairing_ok": ok,
                "pairing_problems": problems,
            },
        )


def run_to_result(spec: RunSpec, prompt: str) -> AgentResult:
    """Drive a graph to completion and return its result.

    The non-streaming path is the streaming path drained — there is no second
    implementation that could disagree with the first.
    """
    graph = AgentGraph(spec)
    answer = ""
    for event in graph.run(prompt):
        if event.type in ("final_answer", "run_completed") and event.payload.get("text"):
            answer = str(event.payload["text"])
    return graph.result(answer)
