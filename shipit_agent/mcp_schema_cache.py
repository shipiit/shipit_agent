"""On-disk MCP tool-schema cache — warm-start an MCP server without spawning it.

Connecting to an MCP server is expensive: for a stdio server it spawns a
subprocess, runs the ``initialize`` handshake, and calls ``tools/list`` — all
before the model has decided to use a single one of its tools. With twenty
connectors attached that is twenty subprocesses and twenty round-trips paid on
every run, most of them never touched.

This module persists the *result* of that discovery — the resolved tool
descriptors — keyed by a fingerprint of the server's configuration. On a warm
start :class:`~shipit_agent.mcp.RemoteMCPServer` rebuilds its tools straight from
the cache and defers the spawn until a tool is actually called (see the ``cache``
flag there). The fingerprint changes when the config changes, and a TTL heals
schema drift, so a stale cache self-corrects.

Design rules (they are the correctness of the thing):
- **Never raise.** A missing / stale / corrupt cache returns ``None`` (a miss)
  with a diagnostic — the caller falls back to a live discovery. A cache must
  never be able to break a run.
- **Atomic writes.** A truncated JSON from a crash mid-write would poison every
  future warm start; we write a temp file and ``os.replace`` it into place.
- **No secrets on disk.** Environment values feed the fingerprint only as a
  hash — never written out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bump when the descriptor shape changes so old caches are ignored, not
#: misread. Part of the on-disk filename, so a version change is a clean miss.
#:
#: Bump it ALSO if the exposed-name resolution ever changes — the cache stores
#: the *resolved* ``exposed_name`` (post-sanitize, post-collision-digest), so a
#: change to ``_sanitize_tool_name`` / ``_MAX_TOOL_NAME_LENGTH`` / the collision
#: logic would otherwise serve stale names from an old cache.
SCHEMA_VERSION = 1

#: Default warm-start freshness window. A cache older than this is a miss, so
#: server-side schema drift heals within a day even if the config never changes.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def cache_dir() -> Path:
    """Where cache files live. ``SHIPIT_MCP_CACHE_DIR`` overrides the default."""
    override = os.getenv("SHIPIT_MCP_CACHE_DIR")
    base = (
        Path(override).expanduser()
        if override
        else Path.home() / ".shipit_agent" / "mcp-cache"
    )
    return base


def _env_hash(env: dict[str, str] | None) -> str:
    """A stable hash of an env mapping — values feed the key but never disk."""
    if not env:
        return "0"
    payload = repr(sorted(env.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def transport_identity(transport: Any) -> str:
    """A stable string identifying *where/what* a transport connects to.

    Stdio transports carry a ``command`` list; HTTP transports an ``endpoint``.
    This plus the env hash is what makes the fingerprint config-specific.
    """
    command = getattr(transport, "command", None)
    if command:
        return "stdio:" + " ".join(str(part) for part in command)
    endpoint = getattr(transport, "endpoint", None) or getattr(transport, "url", None)
    if endpoint:
        return f"http:{endpoint}"
    return f"opaque:{type(transport).__name__}"


def fingerprint(
    *,
    name: str,
    identity: str,
    protocol_version: str,
    allowed: set[str] | None,
    blocked: set[str],
    include_server_in_tool_names: bool,
    env: dict[str, str] | None,
) -> str:
    """Config fingerprint — any change here means a different cache file.

    Sets are sorted before hashing (set iteration order is not stable), the env
    is folded in as a hash, and the exposed-name toggle is included because it
    changes the very names we would cache.
    """
    parts = [
        f"v{SCHEMA_VERSION}",
        name,
        identity,
        protocol_version,
        "allowed=" + (",".join(sorted(allowed)) if allowed is not None else "*"),
        "blocked=" + ",".join(sorted(blocked)),
        f"prefix={int(include_server_in_tool_names)}",
        f"env={_env_hash(env)}",
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest


def _path_for(name: str, fp: str) -> Path:
    # A filesystem-safe slug of the server name keeps files eyeball-identifiable
    # while the fingerprint guarantees uniqueness.
    slug = (
        "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:40] or "mcp"
    )
    return cache_dir() / f"{slug}-{fp}.json"


def load(
    name: str, fp: str, *, ttl: float = DEFAULT_TTL_SECONDS
) -> list[dict[str, Any]] | None:
    """Return cached tool descriptors, or ``None`` on any miss.

    A miss is: no file, a TTL-expired file, a wrong schema version, or an
    unreadable/corrupt file. Every failure path logs and returns ``None`` — the
    caller then does a live discovery. This never raises.
    """
    path = _path_for(name, fp)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as err:  # permissions, etc. — treat as a miss
        logger.debug(
            "MCP schema cache unreadable for %s (%s); doing live discovery", name, err
        )
        return None
    try:
        payload = json.loads(raw)
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if not isinstance(payload.get("tools"), list):
            return None
        age = time.time() - float(payload.get("saved_at", 0))
        if age < 0 or age > ttl:
            return None
        return list(payload["tools"])
    except (ValueError, TypeError) as err:  # corrupt / truncated JSON
        logger.warning(
            "MCP schema cache for %s is corrupt (%s); ignoring it", name, err
        )
        return None


def save(
    name: str, fp: str, tools: list[dict[str, Any]], *, saved_at: float | None = None
) -> None:
    """Persist tool descriptors atomically. Best-effort — never raises.

    ``saved_at`` is injectable so tests are deterministic; production passes the
    wall clock.
    """
    path = _path_for(name, fp)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "server": name,
        "fingerprint": fp,
        "saved_at": saved_at if saved_at is not None else time.time(),
        "tools": tools,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Temp file in the same dir → os.replace is atomic on the same filesystem.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
            os.replace(tmp, path)
        finally:
            # If os.replace already consumed tmp this is a no-op; if we failed
            # before it, clean up the stray temp file.
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError as err:
        logger.debug("could not write MCP schema cache for %s (%s)", name, err)


def invalidate(name: str, fp: str) -> None:
    """Remove one cached schema snapshot, best-effort and idempotently."""
    try:
        _path_for(name, fp).unlink(missing_ok=True)
    except OSError as err:
        logger.debug("could not invalidate MCP schema cache for %s (%s)", name, err)
