"""Parse a connector ``manifest.yaml`` into a :class:`Connector`.

The manifest is the declarative, no-code definition of an integration — one per
directory under ``catalog/``. This module is the single place that knows the
on-disk shape, so the rest of the system only ever sees a validated
:class:`Connector`. Invalid manifests raise :class:`ManifestError` with a clear
message; the loader turns that into a skipped-with-diagnostic, never a crash.

Schema (v1)::

    manifest_version: 1
    name: linear
    description: Linear issues, cycles, projects and comments.
    category: developer
    icon: "📐"
    source: https://linear.app/docs/mcp
    transport:
      type: http            # http (hosted) | stdio (local subprocess)
      url: https://mcp.linear.app/sse
      # for stdio: command / args / env
    auth:
      type: oauth           # oauth | api_key | none
      provider: linear      # key into integrations.oauth.OAUTH_PRESETS
      scopes: [read, write]
      env: [{name: LINEAR_API_KEY, secret: true, required: true}]   # api_key
    tools:
      default_enabled: [list_issues, create_issue]   # token-pruning allow-list
    suggest:
      keywords: [linear, issue, ticket]
"""

from __future__ import annotations

import re
from typing import Any

from .base import Connector

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class ManifestError(ValueError):
    """A manifest is missing a required field or has an invalid value."""


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ManifestError(f"missing required field '{key}'")
    return data[key]


def parse_manifest(data: dict[str, Any]) -> Connector:
    """Validate a manifest dict and build a :class:`Connector`."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a mapping")
    version = data.get("manifest_version", 1)
    if version != 1:
        raise ManifestError(f"unsupported manifest_version {version!r} (expected 1)")

    name = str(_require(data, "name")).strip()
    if not _NAME.match(name):
        raise ManifestError(f"invalid name {name!r} (allowed: A-Z a-z 0-9 _ -)")
    description = str(_require(data, "description")).strip()

    transport = data.get("transport") or {}
    ttype = str(transport.get("type") or "stdio").lower()
    if ttype not in ("http", "stdio"):
        raise ManifestError(f"transport.type must be 'http' or 'stdio', got {ttype!r}")
    kind = "hosted" if ttype == "http" else "stdio"

    url = str(transport.get("url") or "")
    if kind == "hosted" and not url:
        raise ManifestError("hosted (http) transport needs transport.url")

    command_raw = transport.get("command") or []
    command = command_raw.split() if isinstance(command_raw, str) else list(command_raw)
    args = list(transport.get("args") or [])
    if kind == "stdio" and not command:
        raise ManifestError("stdio transport needs transport.command")

    auth = data.get("auth") or {}
    atype = str(auth.get("type") or "none").lower()
    if atype not in ("oauth", "api_key", "none"):
        raise ManifestError(f"auth.type must be oauth|api_key|none, got {atype!r}")
    env_specs = auth.get("env") or []
    env_names = [str(e["name"]) for e in env_specs if isinstance(e, dict) and e.get("name")]
    # Normalise to the Connector's auth vocabulary: an api_key that comes from
    # an env var is "env"; keep "oauth"/"none" as-is.
    conn_auth = "env" if atype == "api_key" and env_names else atype

    tools = (data.get("tools") or {}).get("default_enabled") or []
    suggest = (data.get("suggest") or {}).get("keywords") or []

    return Connector(
        name=name,
        description=description,
        category=str(data.get("category") or "other"),
        kind=kind,
        command=command,
        args=args,
        static_env=dict(transport.get("env") or {}),
        url=url,
        accepts_args=bool(transport.get("accepts_args", False)),
        auth=conn_auth,
        env=env_names,
        oauth=str(auth.get("provider") or (name if atype == "oauth" else "")),
        scopes=[str(s) for s in (auth.get("scopes") or [])],
        tools=[str(t) for t in tools],
        icon=str(data.get("icon") or ""),
        docs=str(data.get("source") or ""),
        suggest=[str(k) for k in suggest],
    )
