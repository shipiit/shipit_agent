"""One connector, one manifest.

A :class:`Connector` is a small, declarative description of an integration —
where it lives (a hosted URL or a local command), how it authenticates, and the
default scopes/tools. Each connector is its own clean module under
``connectors/catalog/`` that constructs one of these and registers it; nothing
here fetches anything or holds a secret.

The manifest is the single source of truth the rest of the system reads:
``connect()`` turns it into a live MCP server, the OAuth layer reads ``oauth``
and ``scopes`` to run a per-user grant, and a UI reads ``category``/``icon`` to
render a catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Connector:
    """A declarative integration definition."""

    #: Catalog key, e.g. ``"linear"``. Lowercase, no spaces.
    name: str
    #: One line for a catalog card / tool description.
    description: str
    #: Grouping for the catalog UI (see ``registry.connector_categories``).
    category: str = "other"
    #: ``"hosted"`` (vendor-run, reached at ``url``) or ``"stdio"`` (a local
    #: server launched from ``command``).
    kind: str = "stdio"

    # ── transport ───────────────────────────────────────────────────────
    #: stdio launch command, e.g. ``["npx", "-y", "@…/server-slack"]``.
    command: list[str] = field(default_factory=list)
    #: fixed positional args for the stdio command.
    args: list[str] = field(default_factory=list)
    #: non-secret static env for the stdio subprocess.
    static_env: dict[str, str] = field(default_factory=dict)
    #: hosted MCP endpoint (Streamable-HTTP/SSE), e.g. ``https://mcp.linear.app/sse``.
    url: str = ""
    #: stdio server that takes extra positional args (filesystem roots, DSNs).
    accepts_args: bool = False

    # ── auth ────────────────────────────────────────────────────────────
    #: ``"none"`` · ``"env"`` (token/key from an env var) · ``"oauth"``
    #: (per-user bearer, obtained via the OAuth flow) · ``"api_key"``.
    auth: str = "none"
    #: env var name(s) a stdio/env-auth server needs (validated up front).
    env: list[str] = field(default_factory=list)
    #: key into ``integrations.oauth.OAUTH_PRESETS`` — the provider whose
    #: authorize/token/refresh endpoints run this connector's OAuth flow.
    oauth: str = ""
    #: default OAuth scopes to request for this connector.
    scopes: list[str] = field(default_factory=list)

    # ── curation / presentation ─────────────────────────────────────────
    #: optional allow-list of tool names to expose (empty = every tool).
    tools: list[str] = field(default_factory=list)
    #: emoji or short glyph for a catalog card.
    icon: str = ""
    #: docs / setup URL.
    docs: str = ""
    #: keywords that hint this connector is relevant (auto-suggest in a UI).
    suggest: list[str] = field(default_factory=list)

    @property
    def hosted(self) -> bool:
        return self.kind == "hosted"

    @property
    def required_env(self) -> list[str]:
        """Compat alias for :attr:`env` — env vars this connector needs."""
        return self.env

    @property
    def uses_oauth(self) -> bool:
        return self.auth == "oauth"
