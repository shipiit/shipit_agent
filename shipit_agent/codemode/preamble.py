"""The child-side `env` — a proxy with no secrets in it.

This module is read as *source text* and prepended to the model's code before
it runs in the sandbox. It cannot import anything from shipit, because the
whole point is that the sandbox holds no tools, no credentials, and no
permission engine — only a socket it can send JSON requests to.

Keep it dependency-free and standard-library-only for that reason.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["PREAMBLE", "build_preamble"]

# NOTE: this is a source template, not imported code. It runs in the child.
PREAMBLE = '''
# ── shipit code mode: the env bridge ─────────────────────────────────────
# Injected automatically. `env` proxies calls to the parent process, which
# holds the credentials and applies the permission policy. Nothing sensitive
# lives in here.
import json as _json
import os as _os
import socket as _socket
import sys as _sys


class _BridgeError(RuntimeError):
    """An env call the parent refused or could not complete."""


class _Bridge:
    def __init__(self):
        self._token = _os.environ.get("SHIPIT_BRIDGE_TOKEN", "")
        kind = _os.environ.get("SHIPIT_BRIDGE_KIND", "")
        if kind == "unix":
            self._sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            self._sock.connect(_os.environ.get("SHIPIT_BRIDGE_PATH", ""))
        elif kind == "tcp":
            self._sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            self._sock.connect((
                _os.environ.get("SHIPIT_BRIDGE_HOST", "127.0.0.1"),
                int(_os.environ.get("SHIPIT_BRIDGE_PORT", "0")),
            ))
        else:
            raise _BridgeError(
                "env is not available: this code was not started by the agent."
            )
        self._reader = self._sock.makefile("r", encoding="utf-8")
        self._writer = self._sock.makefile("w", encoding="utf-8")
        self._next_id = 0

    def call(self, binding, method, kwargs):
        self._next_id += 1
        self._writer.write(_json.dumps({
            "id": self._next_id,
            "token": self._token,
            "binding": binding,
            "method": method,
            "kwargs": kwargs,
        }) + "\\n")
        self._writer.flush()
        line = self._reader.readline()
        if not line:
            raise _BridgeError("the agent closed the connection")
        response = _json.loads(line)
        if not response.get("ok"):
            raise _BridgeError(response.get("error") or "the call was refused")
        return response.get("result", "")


_BRIDGE = None


def _bridge():
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = _Bridge()
    return _BRIDGE


class _Method:
    __slots__ = ("_binding", "_name")

    def __init__(self, binding, name):
        self._binding = binding
        self._name = name

    def __call__(self, **kwargs):
        return _bridge().call(self._binding, self._name, kwargs)

    def __repr__(self):
        return "<env.%s.%s>" % (self._binding, self._name)


class _Binding:
    __slots__ = ("_name", "_methods")

    def __init__(self, name, methods):
        self._name = name
        self._methods = list(methods)

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        if item not in self._methods:
            raise AttributeError(
                "env.%s has no method %r. Available: %s"
                % (self._name, item, ", ".join(self._methods) or "(none)")
            )
        return _Method(self._name, item)

    def __dir__(self):
        return list(self._methods)

    def __repr__(self):
        return "<env.%s: %s>" % (self._name, ", ".join(self._methods))


class _Env:
    __slots__ = ("_bindings",)

    def __init__(self, spec):
        self._bindings = {n: _Binding(n, m) for n, m in spec.items()}

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        if item not in self._bindings:
            raise AttributeError(
                "No binding named %r. Available: %s"
                % (item, ", ".join(sorted(self._bindings)) or "(none)")
            )
        return self._bindings[item]

    def __dir__(self):
        return sorted(self._bindings)

    def __repr__(self):
        return "<env: %s>" % ", ".join(sorted(self._bindings))


env = _Env(__SHIPIT_BINDING_SPEC__)
# ── end of injected preamble ─────────────────────────────────────────────
'''


def build_preamble(bindings: dict) -> str:
    """Render the preamble for a specific set of bindings.

    The spec is inlined as a literal rather than fetched over the bridge, so
    an attribute error on a typo'd method is raised in the child immediately
    instead of costing a round trip — and so the child can `dir(env)`.
    """
    import json

    spec = {
        name: sorted(binding.methods)
        for name, binding in sorted(bindings.items())
    }
    return PREAMBLE.replace("__SHIPIT_BINDING_SPEC__", json.dumps(spec))


def preamble_line_count(bindings: dict) -> int:
    """Lines the preamble occupies, so a traceback can be re-based onto the
    model's own code rather than pointing into injected plumbing."""
    return build_preamble(bindings).count("\n")
