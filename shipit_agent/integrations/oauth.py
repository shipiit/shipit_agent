from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import parse, request


@dataclass(slots=True)
class OAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]
    authorize_url: str
    token_url: str
    extras: dict[str, Any] | None = None


class OAuthStateStore(Protocol):
    def save(self, state: str, payload: dict[str, Any]) -> None: ...

    def load(self, state: str) -> dict[str, Any] | None: ...

    def delete(self, state: str) -> None: ...


class InMemoryOAuthStateStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def save(self, state: str, payload: dict[str, Any]) -> None:
        self._items[state] = dict(payload)

    def load(self, state: str) -> dict[str, Any] | None:
        return self._items.get(state)

    def delete(self, state: str) -> None:
        self._items.pop(state, None)


class FileOAuthStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load_all(self) -> dict[str, dict[str, Any]]:
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: str, payload: dict[str, Any]) -> None:
        data = self._load_all()
        data[state] = dict(payload)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, state: str) -> dict[str, Any] | None:
        return self._load_all().get(state)

    def delete(self, state: str) -> None:
        data = self._load_all()
        if state in data:
            del data[state]
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class OAuthHelper:
    def __init__(
        self, config: OAuthClientConfig, *, state_store: OAuthStateStore | None = None
    ) -> None:
        self.config = config
        self.state_store = state_store or InMemoryOAuthStateStore()

    def create_authorization_url(
        self,
        *,
        state_payload: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        state = secrets.token_urlsafe(24)
        self.state_store.save(state, state_payload or {})
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "response_type": "code",
            "state": state,
            **(self.config.extras or {}),
            **(extra_params or {}),
        }
        return {
            "state": state,
            "url": f"{self.config.authorize_url}?{parse.urlencode(params)}",
        }

    def exchange_code(
        self, *, code: str, state: str | None = None
    ) -> dict[str, Any]:
        """Exchange an authorization ``code`` for tokens.

        Pass the ``state`` returned to your redirect URI to validate it
        against the nonce stored by :meth:`create_authorization_url` — this
        is the CSRF defense for the OAuth flow. The nonce is consumed (single
        use) on a successful match.

        .. warning::
            If ``state`` is omitted the CSRF check is **skipped** for
            backward compatibility. Always pass the callback ``state`` in
            production; an unvalidated flow is vulnerable to login-CSRF and
            nonce replay.
        """
        if state is not None:
            stored = self.state_store.load(state)
            if stored is None:
                raise ValueError(
                    "Invalid or expired OAuth state — possible CSRF or replay."
                )
            # Consume the nonce so it can't be replayed.
            delete = getattr(self.state_store, "delete", None)
            if callable(delete):
                delete(state)

        payload = parse.urlencode(
            {
                "code": code,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": self.config.redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")
        req = request.Request(
            self.config.token_url,
            data=payload,
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        return _stamp_expiry(dict(json.loads(raw)))

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a ``refresh_token`` for a fresh access token.

        This is the single most important piece of a durable connection: an
        access token lives an hour or two, a refresh token for weeks or months.
        Call this when :func:`token_is_expired` says the stored token is at or
        near expiry, then persist the returned token dict. Providers that do not
        return a new ``refresh_token`` keep the old one — carry it forward.

        Returns the token payload stamped with ``expires_at`` (epoch seconds).
        Raises on an HTTP error so a revoked/expired refresh token surfaces as a
        re-connect prompt rather than a silent unauthenticated call.
        """
        payload = parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            }
        ).encode("utf-8")
        req = request.Request(
            self.config.token_url,
            data=payload,
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        token = _stamp_expiry(dict(json.loads(raw)))
        # Providers that rotate refresh tokens return a new one; those that
        # don't omit it — keep the caller's so the chain never breaks.
        token.setdefault("refresh_token", refresh_token)
        return token


def _stamp_expiry(token: dict[str, Any]) -> dict[str, Any]:
    """Add an absolute ``expires_at`` (epoch) from a relative ``expires_in``."""
    import time

    if "expires_at" not in token and token.get("expires_in"):
        try:
            token["expires_at"] = int(time.time()) + int(token["expires_in"])
        except (TypeError, ValueError):
            pass
    return token


def token_is_expired(token: dict[str, Any], *, skew_seconds: int = 120) -> bool:
    """True when a stored OAuth token should be refreshed before use.

    Reads ``expires_at`` (epoch seconds), refreshing ``skew_seconds`` early so
    a call never goes out on a token about to die. A token with no expiry is
    treated as still valid (some providers issue non-expiring tokens).
    """
    import time

    expires_at = token.get("expires_at")
    if not expires_at:
        return False
    try:
        return int(expires_at) - skew_seconds <= int(time.time())
    except (TypeError, ValueError):
        return False


class GoogleOAuthHelper(OAuthHelper):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: list[str],
        state_store: OAuthStateStore | None = None,
    ) -> None:
        super().__init__(
            OAuthClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scopes=scopes,
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                extras={"access_type": "offline", "prompt": "consent"},
            ),
            state_store=state_store,
        )


class SlackOAuthHelper(OAuthHelper):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: list[str],
        state_store: OAuthStateStore | None = None,
    ) -> None:
        super().__init__(
            OAuthClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scopes=scopes,
                authorize_url="https://slack.com/oauth/v2/authorize",
                token_url="https://slack.com/api/oauth.v2.access",
            ),
            state_store=state_store,
        )


def _preset(authorize_url: str, token_url: str, extras: dict[str, Any] | None = None):
    """Build an OAuthHelper factory bound to one provider's endpoints."""

    def factory(
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: list[str],
        state_store: OAuthStateStore | None = None,
    ) -> OAuthHelper:
        return OAuthHelper(
            OAuthClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scopes=scopes,
                authorize_url=authorize_url,
                token_url=token_url,
                extras=extras,
            ),
            state_store=state_store,
        )

    return factory


#: One-line OAuth for the common connectors — each returns a configured
#: ``OAuthHelper`` (authorize → exchange → refresh) for that provider::
#:
#:     helper = OAUTH_PRESETS["github"](cid, secret, redirect, scopes=[...])
#:     url = helper.create_authorization_url()["url"]
#:     token = helper.exchange_code(code=code, state=state)
#:     # later, when token_is_expired(token):
#:     token = helper.refresh_token(token["refresh_token"])
OAUTH_PRESETS = {
    "github": _preset(
        "https://github.com/login/oauth/authorize",
        "https://github.com/login/oauth/access_token",
    ),
    "gitlab": _preset(
        "https://gitlab.com/oauth/authorize",
        "https://gitlab.com/oauth/token",
    ),
    "notion": _preset(
        "https://api.notion.com/v1/oauth/authorize",
        "https://api.notion.com/v1/oauth/token",
        {"owner": "user"},
    ),
    "linear": _preset(
        "https://linear.app/oauth/authorize",
        "https://api.linear.app/oauth/token",
    ),
    "atlassian": _preset(  # Jira + Confluence
        "https://auth.atlassian.com/authorize",
        "https://auth.atlassian.com/oauth/token",
        {"audience": "api.atlassian.com", "prompt": "consent"},
    ),
    "microsoft": _preset(  # Teams, Outlook, Graph
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    ),
    "discord": _preset(
        "https://discord.com/oauth2/authorize",
        "https://discord.com/api/oauth2/token",
    ),
    "asana": _preset(
        "https://app.asana.com/-/oauth_authorize",
        "https://app.asana.com/-/oauth_token",
    ),
    "hubspot": _preset(
        "https://app.hubspot.com/oauth/authorize",
        "https://api.hubapi.com/oauth/v1/token",
    ),
    "zoom": _preset(
        "https://zoom.us/oauth/authorize",
        "https://zoom.us/oauth/token",
    ),
    # ── communication ──
    "google": _preset(
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        {"access_type": "offline", "prompt": "consent"},
    ),
    "slack": _preset(
        "https://slack.com/oauth/v2/authorize",
        "https://slack.com/api/oauth.v2.access",
    ),
    "intercom": _preset(
        "https://app.intercom.com/oauth",
        "https://api.intercom.io/auth/eagle/token",
    ),
    "calendly": _preset(
        "https://auth.calendly.com/oauth/authorize",
        "https://auth.calendly.com/oauth/token",
    ),
    # ── dev & infra ──
    "bitbucket": _preset(
        "https://bitbucket.org/site/oauth2/authorize",
        "https://bitbucket.org/site/oauth2/access_token",
    ),
    "vercel": _preset(
        "https://vercel.com/oauth/authorize",
        "https://api.vercel.com/v2/oauth/access_token",
    ),
    "netlify": _preset(
        "https://app.netlify.com/authorize",
        "https://api.netlify.com/oauth/token",
    ),
    "supabase": _preset(
        "https://api.supabase.com/v1/oauth/authorize",
        "https://api.supabase.com/v1/oauth/token",
    ),
    "sentry": _preset(
        "https://sentry.io/oauth/authorize/",
        "https://sentry.io/oauth/token/",
    ),
    "webflow": _preset(
        "https://webflow.com/oauth/authorize",
        "https://api.webflow.com/oauth/access_token",
    ),
    "figma": _preset(
        "https://www.figma.com/oauth",
        "https://api.figma.com/v1/oauth/token",
    ),
    # ── project & CRM ──
    "monday": _preset(
        "https://auth.monday.com/oauth2/authorize",
        "https://auth.monday.com/oauth2/token",
    ),
    "clickup": _preset(
        "https://app.clickup.com/api",
        "https://api.clickup.com/api/v2/oauth/token",
    ),
    "pipedrive": _preset(
        "https://oauth.pipedrive.com/oauth/authorize",
        "https://oauth.pipedrive.com/oauth/token",
    ),
    "salesforce": _preset(
        "https://login.salesforce.com/services/oauth2/authorize",
        "https://login.salesforce.com/services/oauth2/token",
    ),
    "airtable": _preset(
        "https://airtable.com/oauth2/v1/authorize",
        "https://airtable.com/oauth2/v1/token",
    ),
    "todoist": _preset(
        "https://todoist.com/oauth/authorize",
        "https://todoist.com/oauth/access_token",
    ),
    # ── files & storage ──
    "dropbox": _preset(
        "https://www.dropbox.com/oauth2/authorize",
        "https://api.dropboxapi.com/oauth2/token",
        {"token_access_type": "offline"},
    ),
    "box": _preset(
        "https://account.box.com/api/oauth2/authorize",
        "https://api.box.com/oauth2/token",
    ),
    # ── payments & commerce ──
    "stripe": _preset(  # Stripe Connect
        "https://connect.stripe.com/oauth/authorize",
        "https://connect.stripe.com/oauth/token",
    ),
    "paypal": _preset(
        "https://www.paypal.com/connect",
        "https://api-m.paypal.com/v1/oauth2/token",
    ),
    "square": _preset(
        "https://connect.squareup.com/oauth2/authorize",
        "https://connect.squareup.com/oauth2/token",
    ),
    "shopify": _preset(  # {shop} substituted by the caller in the URLs
        "https://{shop}.myshopify.com/admin/oauth/authorize",
        "https://{shop}.myshopify.com/admin/oauth/access_token",
    ),
    # ── social & content ──
    "twitter": _preset(  # X / OAuth2 PKCE
        "https://twitter.com/i/oauth2/authorize",
        "https://api.twitter.com/2/oauth2/token",
    ),
    "reddit": _preset(
        "https://www.reddit.com/api/v1/authorize",
        "https://www.reddit.com/api/v1/access_token",
        {"duration": "permanent"},
    ),
    "spotify": _preset(
        "https://accounts.spotify.com/authorize",
        "https://accounts.spotify.com/api/token",
    ),
    "twitch": _preset(
        "https://id.twitch.tv/oauth2/authorize",
        "https://id.twitch.tv/oauth2/token",
    ),
    "mailchimp": _preset(
        "https://login.mailchimp.com/oauth2/authorize",
        "https://login.mailchimp.com/oauth2/token",
    ),
}
