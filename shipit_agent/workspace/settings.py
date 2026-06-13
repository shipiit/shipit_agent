"""Declarative workspace config — ``.shipit/settings.json``.

Check a policy into the repo: permissions (allow/deny/ask + mode), env vars, and
a default model. A user-global ``~/.shipit/settings.json`` is merged underneath
the project file. Wires straight into the permission engine (the control plane).

Example ``.shipit/settings.json``::

    {
      "model": "bedrock/us.anthropic.claude-3-5-sonnet-20240620-v1:0",
      "permissions": {
        "mode": "default",
        "deny": ["bash", "*_delete"],
        "ask": ["sql"],
        "allow": ["read*", "grep*"]
      },
      "env": { "SHIPIT_LLM_PROVIDER": "bedrock" }
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WorkspaceSettings:
    permission_mode: str = "default"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_permission_engine(self) -> Any:
        """Build a ``PermissionEngine`` from these settings, or ``None``.

        Returns ``None`` when nothing constrains tools (default mode, no rules)
        so the agent stays unrestricted unless the file asks otherwise.
        """
        if self.permission_mode == "default" and not (
            self.allow or self.deny or self.ask
        ):
            return None
        from shipit_agent.permissions import PermissionEngine

        return PermissionEngine(
            mode=self.permission_mode,  # type: ignore[arg-type]
            allow=list(self.allow),
            deny=list(self.deny),
            ask=list(self.ask),
        )

    def apply_env(self) -> None:
        """Set any declared env vars that aren't already set."""
        for key, value in self.env.items():
            os.environ.setdefault(str(key), str(value))


def settings_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".shipit" / "settings.json"


def load_settings(
    project_root: str | Path, *, include_user: bool = True
) -> WorkspaceSettings:
    """Merge ``~/.shipit/settings.json`` (user) then ``.shipit/settings.json``."""
    merged: dict[str, Any] = {}
    candidates: list[Path] = []
    if include_user:
        candidates.append(Path(os.path.expanduser("~/.shipit/settings.json")))
    candidates.append(settings_path(project_root))

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            merged.update(data)

    perms = merged.get("permissions") or {}
    return WorkspaceSettings(
        permission_mode=str(perms.get("mode", merged.get("permission_mode", "default"))),
        allow=list(perms.get("allow", [])),
        deny=list(perms.get("deny", [])),
        ask=list(perms.get("ask", [])),
        env={str(k): str(v) for k, v in (merged.get("env") or {}).items()},
        model=merged.get("model"),
        raw=merged,
    )
