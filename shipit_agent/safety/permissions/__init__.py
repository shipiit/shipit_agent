"""Permission engine — a fast, rule-based control plane for tool calls.

A rule-based permission layer: every proposed tool call is
checked against declarative **allow / deny / ask** rules and a **mode** before
it runs — no LLM required (unlike :mod:`shipit_agent.verifier`, which is an
*LLM* veto and complements this). The two can run together: the permission
engine is the cheap first gate; the verifier is the smart second opinion.

Modes:

- ``default``     — apply rules; unmatched tools fall back to ``default_decision``.
- ``acceptEdits`` — auto-allow file edit/write tools; everything else via rules.
- ``plan``        — read-only gate: only known read-only tools run; every
                    mutating/unknown tool is denied so the agent must produce a
                    plan instead of acting.
- ``bypass``      — allow everything not denied or asked (``bypassPermissions``
                    is accepted too, the Claude Agent SDK's name).
- ``dontAsk``     — never ask: anything not pre-approved by an allow rule or the
                    callback is refused.

Rules are applied in the Claude Agent SDK's order: deny rules, then ask rules,
then the mode, then allow rules, then the callback. An ask rule is a request
for a human, so no mode or broad allow pattern overrides it.

A check returns a :class:`PermissionResult` with a decision and, optionally,
``updated_arguments`` to **rewrite** the tool call (e.g. redact a secret, scope
a path) before it executes.
"""

from __future__ import annotations

from .engine import PermissionEngine
from .gate import authorize_tool, coerce_permissions
from .values import PermissionDecision, PermissionMode, PermissionResult

__all__ = [
    "PermissionDecision",
    "PermissionEngine",
    "PermissionMode",
    "PermissionResult",
    "authorize_tool",
    "coerce_permissions",
]
