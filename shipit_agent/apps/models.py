"""App names, manifests, apps and blueprints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENTRYPOINT = "app.py"


_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def validate_name(name: str) -> str:
    """App names double as binding names and directory names.

    Rejected early and by one rule, rather than producing a directory that
    cannot later be referenced from `env`.
    """
    if not _NAME.match(name or ""):
        raise ValueError(
            f"Invalid app name {name!r}: use lower snake case, 2-41 characters, "
            "starting with a letter."
        )
    return name


@dataclass(slots=True)
class AppManifest:
    """What an app is, and what it is allowed to reach."""

    name: str
    title: str
    description: str = ""
    entrypoint: str = ENTRYPOINT
    # binding name inside the app → binding name in the agent's env
    bindings: dict[str, str] = field(default_factory=dict)
    blueprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "bindings": dict(self.bindings),
            "blueprint": self.blueprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppManifest":
        return cls(
            name=str(data.get("name") or ""),
            title=str(data.get("title") or data.get("name") or ""),
            description=str(data.get("description") or ""),
            entrypoint=str(data.get("entrypoint") or ENTRYPOINT),
            bindings=dict(data.get("bindings") or {}),
            blueprint=data.get("blueprint"),
        )


@dataclass(slots=True)
class App:
    """An app on disk."""

    path: Path
    manifest: AppManifest

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def entrypoint(self) -> Path:
        return self.path / self.manifest.entrypoint

    def files(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.path))
            for p in self.path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )

    def describe(self) -> str:
        lines = [f"{self.manifest.title} (`{self.name}`)"]
        if self.manifest.description:
            lines.append(self.manifest.description)
        lines.append(f"files    : {', '.join(self.files())}")
        wired = self.manifest.bindings
        lines.append(
            "bindings : "
            + (", ".join(f"{k} ← {v}" for k, v in sorted(wired.items())) or "none")
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Blueprint:
    """A starting file tree, plus what the agent still has to wire up."""

    id: str
    title: str
    description: str
    files: dict[str, str]
    expects: tuple[str, ...] = ()

    def notes(self) -> str:
        lines = [f"Instantiated blueprint `{self.id}` — {self.description}",
                 f"files: {', '.join(sorted(self.files))}"]
        if self.expects:
            lines.append(
                "wire these before using it: " + ", ".join(self.expects)
            )
        return "\n".join(lines)

