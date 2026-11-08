"""GitHub pull request reviews and review requests."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput

from .constants import (
    _VALID_REVIEW_EVENTS,
)


class _ReviewActions:
    """GitHub pull request reviews and review requests."""

    def _review_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for review_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        event = str(kwargs.get("event", "")).strip().upper()
        if event not in _VALID_REVIEW_EVENTS:
            return ToolOutput(
                text=(
                    "GitHub: unsupported review event "
                    f"'{event or '(missing)'}' "
                    "(expected one of APPROVE|REQUEST_CHANGES|COMMENT)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_event",
                    "event": event,
                },
            )
        body_payload: dict[str, Any] = {"event": event}
        if kwargs.get("body") is not None:
            body_payload["body"] = str(kwargs.get("body"))
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}/reviews"
        )
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body_payload
        )
        if err is not None:
            return err
        review = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Review submitted on PR #{int(number)}: {event} "
                f"(id={review.get('id', '?')})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "event": event,
                "item": review,
            },
        )

    def _request_review(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for request_review.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        reviewers = kwargs.get("reviewers") or []
        if not isinstance(reviewers, list) or not reviewers:
            return ToolOutput(
                text="GitHub: `reviewers` must be a non-empty list for request_review.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/"
            f"{int(number)}/requested_reviewers"
        )
        payload, err = self._request_or_error(
            record=record,
            method="POST",
            path=path,
            body={"reviewers": [str(r) for r in reviewers]},
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Requested review on PR #{int(number)} from "
                f"{', '.join(str(r) for r in reviewers)}."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "reviewers": list(reviewers),
                "item": pr,
            },
        )
