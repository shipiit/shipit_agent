"""Figma file, node and image actions."""

from __future__ import annotations

from shipit_agent.tools.base import ToolOutput

from .constants import _VALID_IMAGE_FORMATS


class _FileActions:
    """Figma file, node and image actions."""

    def _get_file(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        file_key = str(parts["file_key"]).strip()
        path = f"/v1/files/{file_key}"
        payload, err = self._request_or_error(record=record, method="GET", path=path)
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        document = data.get("document", {}) if isinstance(data, dict) else {}
        pages = document.get("children", []) if isinstance(document, dict) else []
        name = data.get("name", "(untitled)")
        last_modified = data.get("lastModified", "?")
        text = (
            f"Figma file: {name}\n"
            f"  last_modified: {last_modified}\n"
            f"  pages: {len(pages)}"
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "file": data,
            },
        )

    def _get_file_nodes(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        ids = kwargs.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return ToolOutput(
                text="Figma: `ids` must be a non-empty list for get_file_nodes.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["ids"],
                },
            )
        file_key = str(parts["file_key"]).strip()
        query = {"ids": ",".join(str(i) for i in ids)}
        path = f"/v1/files/{file_key}/nodes"
        payload, err = self._request_or_error(
            record=record, method="GET", path=path, query=query
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        nodes = data.get("nodes", {}) if isinstance(data, dict) else {}
        found_ids = list(nodes.keys()) if isinstance(nodes, dict) else []
        lines = [f"{nid}: present" for nid in found_ids] or [
            "No nodes returned for the given ids."
        ]
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "ids": [str(i) for i in ids],
                "nodes": nodes,
                "count": len(found_ids),
            },
        )

    def _get_image(self, *, record, action, kwargs):
        parts, err = self._require(kwargs, "file_key")
        if err is not None:
            return err
        ids = kwargs.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return ToolOutput(
                text="Figma: `ids` must be a non-empty list for get_image.",
                metadata={
                    "provider": self.provider,
                    "error": "missing_parameter",
                    "missing": ["ids"],
                },
            )
        fmt = str(kwargs.get("format") or "png").strip().lower()
        if fmt not in _VALID_IMAGE_FORMATS:
            return ToolOutput(
                text=(
                    f"Figma: unsupported image format '{fmt}' "
                    "(expected one of png|jpg|svg|pdf)."
                ),
                metadata={
                    "provider": self.provider,
                    "error": "invalid_format",
                    "format": fmt,
                },
            )
        try:
            scale = float(kwargs.get("scale", 1) or 1)
        except (TypeError, ValueError):
            scale = 1.0
        file_key = str(parts["file_key"]).strip()
        body = {
            "ids": ",".join(str(i) for i in ids),
            "format": fmt,
            "scale": scale,
        }
        path = f"/v1/images/{file_key}"
        payload, err = self._request_or_error(
            record=record, method="POST", path=path, body=body
        )
        if err is not None:
            return err
        data = payload if isinstance(payload, dict) else {}
        images = data.get("images", {}) if isinstance(data, dict) else {}
        lines = [
            f"{node_id}: {url or '(no url)'}"
            for node_id, url in (images.items() if isinstance(images, dict) else [])
        ]
        text = (
            "\n".join(lines)
            if lines
            else "No rendered images returned for the given ids."
        )
        return ToolOutput(
            text=text,
            metadata={
                "provider": self.provider,
                "connected": True,
                "action": action,
                "file_key": file_key,
                "format": fmt,
                "scale": scale,
                "images": images,
                "count": len(lines),
            },
        )
