"""Pre-tool veto — wraps tools so a verifier LLM gets to ALLOW/VETO/REWRITE
each call before it executes.

The wrapper is fully transparent to the agent runtime: it satisfies the
same ``Tool`` protocol as the wrapped tool. Vetoed calls return a
``ToolOutput`` whose text reads as a structured error, so the agent's
existing tool-error handling kicks in and triggers a re-plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

from shipit_agent.parsers.streaming_json import parse_partial_json

from .models import PreToolDecision, VerifierConfig, VerifierVerdict


_PRETOOL_SYSTEM_PROMPT = (
    "You are a strict safety verifier reviewing one proposed tool call from an "
    "AI agent. Decide if the call should proceed.\n\n"
    "Reply with a JSON object EXACTLY in this shape:\n"
    '{"verdict": "allow"|"veto"|"rewrite", "reason": "...", "confidence": 0.0-1.0, '
    '"new_args": {...} or null}\n\n'
    "Veto when:\n"
    "- The call is irrelevant to the agent's stated goal.\n"
    "- The arguments look hallucinated (made-up paths, fake URLs, placeholder text).\n"
    "- The call would do something destructive that wasn't asked for "
    "(deleting data, sending messages, charging money, etc.).\n\n"
    "Rewrite (rare) when the intent is fine but a specific argument is clearly wrong "
    "and there's a single obvious correction.\n\n"
    "Otherwise, allow. Default to allow when in doubt — it's better to let the "
    "agent try than to over-veto. Output ONLY the JSON, no prose."
)


class PreToolVerifier:
    """Calls a verifier LLM before each tool execution."""

    def __init__(
        self,
        *,
        llm: Any,
        config: VerifierConfig | None = None,
    ) -> None:
        self.llm = llm
        self.config = config or VerifierConfig()
        self._call_count = 0

    def check(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        goal: str = "",
        recent_history: list[dict[str, Any]] | None = None,
    ) -> PreToolDecision:
        """Ask the verifier whether the proposed tool call should proceed.

        Returns ``PreToolDecision``. If veto is disabled in the config or the
        per-run cap is hit, returns ALLOW immediately without an LLM call.
        """
        if not self.config.veto_enabled:
            return PreToolDecision(verdict=VerifierVerdict.ALLOW, reason="veto disabled")
        if self._call_count >= self.config.max_pretool_calls_per_run:
            return PreToolDecision(
                verdict=VerifierVerdict.ALLOW, reason="pretool cap reached"
            )

        self._call_count += 1
        user_msg = _build_user_message(tool_name, tool_args, goal, recent_history)
        try:
            text = _invoke(self.llm, _PRETOOL_SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            # Verifier failure must NEVER block the main agent — fail open
            return PreToolDecision(
                verdict=VerifierVerdict.ALLOW,
                reason=f"verifier unavailable: {exc}",
                confidence=0.0,
            )

        decision = _parse_decision(text)

        # Confidence-gating: low-confidence verdicts get downgraded to ALLOW so
        # the verifier doesn't over-block on shaky calls.
        if (
            decision.verdict != VerifierVerdict.ALLOW
            and decision.confidence < self.config.veto_min_confidence
        ):
            return PreToolDecision(
                verdict=VerifierVerdict.ALLOW,
                reason=f"low confidence ({decision.confidence:.2f}); original: {decision.reason}",
                confidence=decision.confidence,
            )
        return decision

    @property
    def call_count(self) -> int:
        return self._call_count


def wrap_tool_with_verifier(
    tool: Any,
    verifier: PreToolVerifier,
    *,
    goal: str = "",
) -> Any:
    """Return a verifier-wrapped clone of ``tool``.

    The wrapper exposes the same ``name``, ``description``, ``schema()``,
    and ``run()`` surface as the wrapped tool but calls ``verifier.check()``
    inside ``run()`` and short-circuits on VETO with a synthetic error result.
    """
    return _VerifyingToolWrapper(inner=tool, verifier=verifier, goal=goal)


class _VerifyingToolWrapper:
    """Tool-protocol wrapper that interposes a pre-call verifier check."""

    def __init__(self, *, inner: Any, verifier: PreToolVerifier, goal: str) -> None:
        self._inner = inner
        self._verifier = verifier
        self._goal = goal

    # Delegate the read-only Tool surface to the inner tool
    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def description(self) -> str:
        return getattr(self._inner, "description", "")

    @property
    def prompt(self) -> str:
        return getattr(self._inner, "prompt", "")

    @property
    def prompt_instructions(self) -> str:
        return getattr(self._inner, "prompt_instructions", "")

    def schema(self) -> dict[str, Any]:
        return self._inner.schema()

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        decision = self._verifier.check(
            tool_name=self._inner.name,
            tool_args=dict(kwargs),
            goal=self._goal,
        )
        if decision.verdict == VerifierVerdict.VETO:
            return _make_veto_output(self._inner.name, decision)
        if decision.verdict == VerifierVerdict.REWRITE and decision.new_args:
            kwargs = dict(decision.new_args)
        if context is None:
            return self._inner.run(**kwargs)
        return self._inner.run(context, **kwargs)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_user_message(
    tool_name: str,
    tool_args: dict[str, Any],
    goal: str,
    recent_history: list[dict[str, Any]] | None,
) -> str:
    parts: list[str] = []
    if goal:
        parts.append(f"Agent goal: {goal}")
    if recent_history:
        # Last 4 messages, truncated for brevity
        tail = recent_history[-4:]
        compact = []
        for m in tail:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:200]
            compact.append(f"  [{role}] {content}")
        parts.append("Recent conversation:\n" + "\n".join(compact))
    parts.append(f"Proposed tool: {tool_name}")
    parts.append(f"Arguments: {json.dumps(tool_args, default=str)[:500]}")
    parts.append("Verdict?")
    return "\n\n".join(parts)


def _invoke(llm: Any, system: str, user: str) -> str:
    if not hasattr(llm, "complete"):
        raise TypeError("verifier LLM must have a .complete(messages=...) method")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = llm.complete(messages=messages)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("content") or result.get("text") or ""
    text_attr = getattr(result, "content", None) or getattr(result, "text", None)
    return text_attr or ""


def _parse_decision(text: str) -> PreToolDecision:
    """Parse the verifier's JSON response into a ``PreToolDecision``."""
    parsed = parse_partial_json(text) or {}
    if not isinstance(parsed, dict):
        return PreToolDecision(
            verdict=VerifierVerdict.ALLOW,
            reason="verifier response not parseable as object",
            confidence=0.0,
        )
    raw_verdict = str(parsed.get("verdict", "allow")).lower().strip()
    verdict = _verdict_from_str(raw_verdict)
    reason = str(parsed.get("reason", ""))[:300]
    confidence = _coerce_float(parsed.get("confidence"), default=0.5)
    new_args = parsed.get("new_args") if isinstance(parsed.get("new_args"), dict) else None
    return PreToolDecision(
        verdict=verdict,
        reason=reason,
        confidence=confidence,
        new_args=new_args,
    )


def _verdict_from_str(s: str) -> VerifierVerdict:
    s = s.lower()
    if "veto" in s or "block" in s or "deny" in s:
        return VerifierVerdict.VETO
    if "rewrite" in s or "modify" in s or "fix" in s:
        return VerifierVerdict.REWRITE
    return VerifierVerdict.ALLOW


def _coerce_float(v: Any, *, default: float) -> float:
    if isinstance(v, (int, float)):
        return float(max(0.0, min(1.0, v)))
    if isinstance(v, str):
        m = re.search(r"-?\d*\.?\d+", v)
        if m:
            try:
                return float(max(0.0, min(1.0, float(m.group()))))
            except ValueError:
                pass
    return default


def _make_veto_output(tool_name: str, decision: PreToolDecision) -> Any:
    """Build a ToolOutput-shaped object for a vetoed call.

    We return a tiny object that quacks like ``ToolOutput`` (text + metadata).
    Importing ``ToolOutput`` would create a circular dep with the tools
    package, so we duck-type it.
    """
    text = (
        f"[verifier-veto] The {tool_name!r} tool call was blocked: {decision.reason} "
        f"(confidence={decision.confidence:.2f}). "
        "Re-plan without this call, or revise the arguments."
    )
    # Lazy-import so module-load doesn't pay this cost
    try:
        from shipit_agent.tools.base import ToolOutput

        return ToolOutput(text=text, metadata={"verifier_veto": True, "reason": decision.reason})
    except Exception:
        return _DuckToolOutput(text=text, metadata={"verifier_veto": True, "reason": decision.reason})


class _DuckToolOutput:
    """Fallback ToolOutput-shape if the real one can't be imported."""

    __slots__ = ("text", "metadata")

    def __init__(self, *, text: str, metadata: dict[str, Any]) -> None:
        self.text = text
        self.metadata = metadata

    def __repr__(self) -> str:
        return f"ToolOutput(text={self.text!r}, metadata={self.metadata!r})"
