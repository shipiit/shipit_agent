"""AppStore: apps saved on disk, one folder each."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .blueprints import BLUEPRINTS
from .models import ENTRYPOINT, App, AppManifest, validate_name
from .runner import run_app

MANIFEST = "app.json"


class AppStore:
    """Apps on disk, under one root."""

    def __init__(
        self, root: str | Path = ".shipit/apps", *, workdir: str | Path | None = None
    ) -> None:
        self.root = Path(root).expanduser()
        # Where an app *runs*. Not the app's own directory: an app given
        # `path="guests.csv"` means the file the agent has been working with,
        # and resolving that against the app's install directory finds
        # nothing. Defaults to the project the apps live under.
        self.workdir = Path(workdir).expanduser() if workdir else self._project_root()

    def _project_root(self) -> Path:
        """`<project>/.shipit/apps` → `<project>`; anything else → its parent."""
        root = self.root.resolve()
        if root.name == "apps" and root.parent.name == ".shipit":
            return root.parent.parent
        return root.parent

    # ── read ─────────────────────────────────────────────────────────────

    def path_for(self, name: str) -> Path:
        return self.root / validate_name(name)

    def exists(self, name: str) -> bool:
        return (self.path_for(name) / MANIFEST).exists()

    def get(self, name: str) -> App:
        path = self.path_for(name)
        manifest_path = path / MANIFEST
        if not manifest_path.exists():
            raise KeyError(f"No app named {name!r} in {self.root}")
        manifest = AppManifest.from_dict(json.loads(manifest_path.read_text()))
        return App(path=path, manifest=manifest)

    def list(self) -> list[App]:
        if not self.root.exists():
            return []
        apps = []
        for child in sorted(self.root.iterdir()):
            if (child / MANIFEST).exists():
                apps.append(self.get(child.name))
        return apps

    # ── write ────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        *,
        title: str,
        description: str = "",
        files: dict[str, str] | None = None,
        blueprint: str | None = None,
        overwrite: bool = False,
    ) -> App:
        """Create an app from a blueprint, explicit files, or both.

        Explicit files win over blueprint files of the same name, so an agent
        can start from a blueprint and replace just the entrypoint.
        """
        validate_name(name)
        path = self.path_for(name)
        if path.exists() and not overwrite and (path / MANIFEST).exists():
            raise FileExistsError(f"App {name!r} already exists at {path}")

        contents: dict[str, str] = {}
        if blueprint is not None:
            if blueprint not in BLUEPRINTS:
                raise KeyError(
                    f"Unknown blueprint {blueprint!r}. Available: "
                    f"{', '.join(sorted(BLUEPRINTS))}"
                )
            contents.update(BLUEPRINTS[blueprint].files)
        contents.update(files or {})
        if ENTRYPOINT not in contents:
            raise ValueError(
                f"An app needs {ENTRYPOINT} defining `run(input, env)` — pass it "
                "in files, or start from a blueprint."
            )

        path.mkdir(parents=True, exist_ok=True)
        for relative, body in contents.items():
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

        manifest = AppManifest(
            name=name, title=title, description=description, blueprint=blueprint
        )
        self._write_manifest(path, manifest)
        return App(path=path, manifest=manifest)

    def run(self, name: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        """Run one of this store's apps, where this store's apps run.

        :func:`run_app` on its own defaults to the app's install directory,
        which is right for an app that only touches its own files and wrong
        for one handed ``path="bookings.csv"``. Going through the store keeps
        the working directory consistent with what the agent's own tools see.
        """
        kwargs.setdefault("cwd", self.workdir)
        return run_app(self.get(name), payload, **kwargs)

    def bind(self, name: str, *, source: str, as_name: str | None = None) -> App:
        """Wire one of the agent's bindings into the app's own env."""
        app = self.get(name)
        app.manifest.bindings[as_name or source] = source
        self._write_manifest(app.path, app.manifest)
        return app

    def unbind(self, name: str, as_name: str) -> App:
        app = self.get(name)
        app.manifest.bindings.pop(as_name, None)
        self._write_manifest(app.path, app.manifest)
        return app

    def delete(self, name: str) -> None:
        import shutil

        path = self.path_for(name)
        if path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _write_manifest(path: Path, manifest: AppManifest) -> None:
        (path / MANIFEST).write_text(
            json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
        )


def app_docstring(app: "App") -> str:
    """The app's module docstring — what it expects, in its own words.

    Returned to the agent when a run fails, because "the app raised KeyError"
    without saying what the app wanted costs a retry that guessing cannot fix.
    """
    try:
        source = app.entrypoint.read_text(encoding="utf-8")
    except OSError:
        return ""
    import ast

    try:
        return (ast.get_docstring(ast.parse(source)) or "").strip()
    except SyntaxError:
        return ""

