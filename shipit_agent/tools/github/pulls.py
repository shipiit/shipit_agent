"""GitHub pull request actions."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput

from .constants import (
    _VALID_MERGE_METHODS,
)


class _PullActions:
    """GitHub pull request actions."""

    def _list_pulls(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        state = str(kwargs.get("state", "open")).strip() or "open"
        query: dict[str, Any] = {"state": state}
        if kwargs.get("per_page") is not None:
            query["per_page"] = int(kwargs["per_page"])
        if kwargs.get("page") is not None:
            query["page"] = int(kwargs["page"])
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        items = payload if isinstance(payload, list) else []
        lines = [
            f"#{item.get('number', '?')} [{item.get('state', '?')}] {item.get('title', '')}"
            for item in items
        ]
        text = "\n".join(lines) if lines else "No GitHub pull requests found."
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "items": items,
                "count": len(items),
            },
        )

    def _get_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for get_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        head = pr.get("head", {}).get("ref", "?")
        base = pr.get("base", {}).get("ref", "?")
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        changed = pr.get("changed_files", 0)
        text = (
            f"#{pr.get('number', number)} [{pr.get('state', '?')}] "
            f"{pr.get('title', '')}\n"
            f"  {head} → {base}  (+{additions}/-{deletions} across {changed} files)"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
            },
        )

    def _create_pull(self, *, record, action, kwargs):
        parts, err = self._require(
            kwargs, "owner", "repo", "title", "head", "base"
        )
        if err is not None:
            return err
        body_payload: dict[str, Any] = {
            "title": str(kwargs.get("title", "")),
            "head": str(kwargs.get("head", "")),
            "base": str(kwargs.get("base", "")),
        }
        if kwargs.get("body") is not None:
            body_payload["body"] = str(kwargs.get("body"))
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body_payload
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Pull request created: #{pr.get('number', '?')} "
                f"{pr.get('title', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
            },
        )

    def _update_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for update_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        body_payload: dict[str, Any] = {}
        for field in ("title", "body", "state"):
            if kwargs.get(field) is not None:
                body_payload[field] = str(kwargs.get(field))
        if not body_payload:
            return ToolOutput(
                text="GitHub: update_pull requires at least one of title/body/state.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        path = f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}"
        payload, err = self._request_or_error(
            record=record, method="PATCH", path=path, body=body_payload
        )
        if err is not None:
            return err
        pr = payload if isinstance(payload, dict) else {}
        return ToolOutput(
            text=(
                f"Pull request #{int(number)} updated "
                f"({', '.join(body_payload.keys())})."
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "item": pr,
                "updated_fields": sorted(body_payload.keys()),
            },
        )

    def _merge_pull(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "owner", "repo")
        if err is not None:
            return err
        number = kwargs.get("number")
        if number is None:
            return ToolOutput(
                text="GitHub: `number` is required for merge_pull.",
                metadata={"provider": self.provider, "error": "missing_parameter"},
            )
        merge_method = str(kwargs.get("merge_method", "merge")).strip() or "merge"
        if merge_method not in _VALID_MERGE_METHODS:
            return ToolOutput(
                text=(
                    "GitHub: unsupported merge_method "
                    f"'{merge_method}' (expected one of merge|squash|rebase)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_merge_method",
                    "merge_method": merge_method,
                },
            )
        path = (
            f"/repos/{parts['owner']}/{parts['repo']}/pulls/{int(number)}/merge"
        )
        payload, err = self._request_or_error(
            record=record,
            method="PUT",
            path=path,
            body={"merge_method": merge_method},
        )
        if err is not None:
            return err
        result = payload if isinstance(payload, dict) else {}
        merged = bool(result.get("merged"))
        return ToolOutput(
            text=(
                f"Pull request #{int(number)} "
                f"{'merged' if merged else 'merge attempt returned'} "
                f"({merge_method}): {result.get('message', '')}"
            ),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "merge_method": merge_method,
                "merged": merged,
                "item": result,
            },
        )
