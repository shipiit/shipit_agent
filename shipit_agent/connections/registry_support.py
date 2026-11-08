"""Names ConnectionRegistry and its discovery methods share."""

from __future__ import annotations

from .models import AuthKind

AUTH_KINDS: dict[str, AuthKind] = {
    "gmail": AuthKind.OAUTH,
    "google_calendar": AuthKind.OAUTH,
    "google_drive": AuthKind.OAUTH,
    "google_sheets": AuthKind.OAUTH,
    "slack": AuthKind.OAUTH,
    "salesforce": AuthKind.OAUTH,
    "linkedin": AuthKind.OAUTH,
    "github": AuthKind.TOKEN,
    "gitlab": AuthKind.TOKEN,
    "figma": AuthKind.TOKEN,
    "notion": AuthKind.TOKEN,
    "linear": AuthKind.API_KEY,
    "jira": AuthKind.API_KEY,
    "confluence": AuthKind.API_KEY,
    "stripe": AuthKind.API_KEY,
    "zendesk": AuthKind.API_KEY,
    "custom_api": AuthKind.API_KEY,
}


TITLES: dict[str, str] = {
    "gmail": "Gmail",
    "google_calendar": "Google Calendar",
    "google_drive": "Google Drive",
    "google_sheets": "Google Sheets",
    "slack": "Slack",
    "linear": "Linear",
    "jira": "Jira",
    "notion": "Notion",
    "confluence": "Confluence",
    "github": "GitHub",
    "gitlab": "GitLab",
    "figma": "Figma",
    "salesforce": "Salesforce",
    "stripe": "Stripe",
    "zendesk": "Zendesk",
    "linkedin": "LinkedIn",
    "custom_api": "Custom API",
}


_SECRET_FIELDS = ("api_key", "token", "access_token", "password", "secret")


def title_for(key: str) -> str:
    """A human-readable title for a connection key."""
    return TITLES.get(key) or key.replace("_", " ").title()

