"""Constants shared by GitHubTool and its action mixins."""

from __future__ import annotations

_DEFAULT_BASE_URL = "https://api.github.com"


_DEFAULT_AUTH_SCHEME = "Bearer"


_VALID_REVIEW_EVENTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}


_VALID_MERGE_METHODS = {"merge", "squash", "rebase"}

