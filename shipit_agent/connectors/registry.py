"""The connector registry — discover, list, and connect by name.

Each module under ``connectors/catalog/`` registers one :class:`Connector`.
``load_catalog()`` imports them all once; ``connect()`` turns a manifest into a
live :class:`RemoteMCPServer` ready for ``Agent(mcps=[...])`` — choosing the
hosted (HTTP/SSE) or stdio transport from the manifest and wiring the per-user
bearer token for OAuth connectors.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from threading import Lock

from ..mcp import (
    MCPStreamableHTTPTransport,
    PersistentMCPSubprocessTransport,
    RemoteMCPServer,
)
from .base import Connector
from .manifests import ManifestError, parse_manifest

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Connector] = {}
#: (path, error) for every manifest that failed to load — surfaced by a UI/CI.
CATALOG_DIAGNOSTICS: list[tuple[str, str]] = []
_loaded = False
_load_lock = Lock()

_CATALOG_DIR = Path(__file__).parent / "catalog"


def register(connector: Connector) -> Connector:
    """Add a connector to the registry (also used by a manifest's parse)."""
    _REGISTRY[connector.name] = connector
    return connector


def load_catalog() -> None:
    """Scan ``catalog/<name>/manifest.yaml`` and register each connector.

    One directory per connector, one declarative manifest each — no code to run.
    Idempotent and thread-safe; an invalid manifest is skipped and recorded in
    :data:`CATALOG_DIAGNOSTICS` rather than breaking the whole catalog. Needs
    PyYAML (``pip install 'shipit-agent[connectors]'``); without it the catalog
    is empty and a one-line hint is logged.
    """
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        try:
            import yaml
        except ImportError:
            logger.warning(
                "connector catalog needs PyYAML — install with "
                "'pip install shipit-agent[connectors]'."
            )
            _loaded = True
            return

        for manifest in sorted(_CATALOG_DIR.glob("*/manifest.yaml")):
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                register(parse_manifest(data))
            except (ManifestError, yaml.YAMLError, OSError) as exc:
                CATALOG_DIAGNOSTICS.append((str(manifest), str(exc)))
                logger.warning("connector manifest %s skipped: %s", manifest.name, exc)
        _loaded = True


def get_connector(name: str) -> Connector | None:
    load_catalog()
    return _REGISTRY.get(name)


def list_connectors(*, category: str | None = None) -> list[Connector]:
    """Every connector, alphabetically; optionally filtered to one category."""
    load_catalog()
    items = [_REGISTRY[k] for k in sorted(_REGISTRY)]
    return [c for c in items if not category or c.category == category]


def connector_categories() -> list[str]:
    load_catalog()
    return sorted({c.category for c in _REGISTRY.values()})


def connect(
    name: str,
    *,
    token: str | None = None,
    env: dict[str, str] | None = None,
    args: list[str] | None = None,
    headers: dict[str, str] | None = None,
    url: str | None = None,
    command: list[str] | None = None,
) -> RemoteMCPServer:
    """Turn a catalog connector into a live MCP server.

    **Hosted** connectors reach the vendor endpoint over Streamable-HTTP/SSE.
    OAuth ones need the connected user's access token — pass ``token=`` (resolve
    + refresh it per user with the OAuth layer); env-auth ones read their key
    from the environment.

    **stdio** connectors launch the official server locally on a persistent
    subprocess, validating required env vars and the launcher binary up front.
    ``command``/``url`` override the manifest entirely (a local build, a proxy).
    """
    c = get_connector(name)
    if c is None and not (url or command):
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown connector '{name}'. Catalog: {known}")

    endpoint = url or (c.url if c else "")
    if endpoint:
        bearer = token
        if not bearer and c and c.auth in ("env", "api_key") and c.env:
            bearer = os.environ.get(c.env[0])
        if c and c.uses_oauth and not bearer:
            raise ValueError(
                f"Connector '{name}' is per-user OAuth — pass token=<access token>. "
                f"Run its OAuth flow (OAUTH_PRESETS['{c.oauth or name}']) and store "
                "the token per user; refresh it when token_is_expired()."
            )
        transport = MCPStreamableHTTPTransport(
            endpoint, headers=headers, bearer_token=bearer
        )
        return RemoteMCPServer(
            name=name, transport=transport, metadata=_meta(c, hosted=True)
        )

    # stdio
    merged_env = {**(env or {})}
    missing = [
        v for v in (c.env if c else []) if not (merged_env.get(v) or os.environ.get(v))
    ]
    if missing:
        raise ValueError(
            f"Connector '{name}' needs env var(s): {', '.join(missing)}. "
            "Pass them via env={...} or export them."
        )
    full = list(command or (c.command if c else []))
    if args:
        full += [str(a) for a in args]
    if not full:
        raise ValueError(f"Connector '{name}' has no launch command.")
    if shutil.which(full[0]) is None:
        raise RuntimeError(
            f"'{full[0]}' is not on PATH — install it to run '{name}' "
            "(npx ships with Node.js; uvx with uv)."
        )
    transport = PersistentMCPSubprocessTransport(full, env=merged_env)
    return RemoteMCPServer(name=name, transport=transport, metadata=_meta(c, hosted=False))


def _meta(c: Connector | None, *, hosted: bool) -> dict[str, object]:
    return {
        "catalog": c.name if c else "",
        "hosted": hosted,
        "category": c.category if c else "other",
        "description": c.description if c else "",
    }
