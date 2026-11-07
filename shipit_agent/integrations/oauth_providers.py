"""Ready-made OAuth helpers and presets for well-known providers."""

from __future__ import annotations

from typing import Any

from .oauth import OAuthClientConfig, OAuthHelper, OAuthStateStore


class GoogleOAuthHelper(OAuthHelper):
    """OAuth helper preconfigured for Google accounts."""
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
    """OAuth helper preconfigured for Slack workspaces."""
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
