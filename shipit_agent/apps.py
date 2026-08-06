"""Apps — something the agent builds once and then *uses*.

Cloudflare OS calls these gadgets. A gadget is a small program the agent
writes into the workspace, wires resources into, and then invokes; in their
transcript it reads `Used the app`, and in their UI it opens in the sidebar.
It is the difference between an agent that answers a question and an agent
that leaves behind something you can run again tomorrow.

The same idea in Python, minus the parts that only exist because their
runtime is Durable Objects on a global network:

    app = store.create("rsvp_report", title="RSVP report",
                       blueprint="report")
    store.bind("rsvp_report", source="SHEETS", name="SHEET")
    result = run_app(app, {"month": "May"}, invoker=…, bindings=…)

An app is a **directory** with a manifest and an `app.py` exporting one
function::

    def run(input: dict, env) -> Any:
        rows = env.SHEET.read(range="A1:D50")
        return {"rows": len(rows)}

Two properties are deliberate and load-bearing:

**An app is not more privileged than the agent that wrote it.** It runs in a
subprocess with no credentials, and `env` reaches the parent over the same
capability bridge `execute_code` uses — so every resource call an app makes is
gated by the permission engine, the contracts and the approval queue exactly
as the equivalent tool call would be.

**An app only sees what it was wired.** Its `env` contains the bindings named
in its manifest, not the agent's whole environment. Wiring is an explicit act
(`set_app_binding`), recorded in the manifest, and visible in the transcript.

Blueprints are starting points, not magic: each is a file tree copied into the
new app, with a note about what the agent still has to wire up.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "App",
    "AppManifest",
    "AppRunResult",
    "AppStore",
    "BLUEPRINTS",
    "Blueprint",
    "run_app",
]

ENTRYPOINT = "app.py"
MANIFEST = "app.json"

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


_REPORT_APP = '''\
"""A report over rows the caller passes in."""


def run(input, env):
    rows = input.get("rows") or []
    if not rows:
        return {"markdown": "_no rows_", "count": 0}

    columns = list(rows[0])
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(c, "")) for c in columns) + " |"
        for row in rows
    ]
    return {"markdown": "\\n".join([header, divider, *body]), "count": len(rows)}
'''

_TABLE_APP = '''\
"""Read a CSV and answer questions about it, every time it is run."""

import csv
from pathlib import Path


def run(input, env):
    path = Path(input["path"])
    with path.open() as handle:
        rows = list(csv.DictReader(handle))

    # `group_by` is the documented name; `column` is what a model reaches for
    # half the time. Accepting both costs nothing and saves a retry.
    column = input.get("group_by") or input.get("column")
    if not column:
        return {"rows": len(rows), "columns": list(rows[0]) if rows else []}

    counts = {}
    for row in rows:
        counts[row.get(column, "")] = counts.get(row.get(column, ""), 0) + 1
    return {"rows": len(rows), "group_by": column, "counts": counts}
'''

_PAGE_APP = '''\
"""Render a self-contained HTML page from data, and write it beside the app."""

import html
from pathlib import Path


def run(input, env):
    title = input.get("title", "Report")
    rows = input.get("rows") or []
    cells = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values())
        + "</tr>"
        for row in rows
    )
    head = "".join(f"<th>{html.escape(c)}</th>" for c in (rows[0] if rows else {}))
    page = (
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
        "<style>body{font:15px/1.6 system-ui;margin:40px;max-width:720px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #e8e6e3;padding:8px 10px;text-align:left}"
        "th{font-weight:600}</style>"
        f"<h1>{html.escape(title)}</h1><table><tr>{head}</tr>{cells}</table>"
    )
    out = Path(input.get("output", "page.html"))
    out.write_text(page, encoding="utf-8")
    return {"path": str(out.resolve()), "bytes": len(page), "rows": len(rows)}
'''


BLUEPRINTS: dict[str, Blueprint] = {
    "report": Blueprint(
        id="report",
        title="Markdown report",
        description="Turns a list of records into a Markdown table.",
        files={ENTRYPOINT: _REPORT_APP},
    ),
    "csv_summary": Blueprint(
        id="csv_summary",
        title="CSV summary",
        description="Reads a CSV and counts rows, optionally grouped by a column.",
        files={ENTRYPOINT: _TABLE_APP},
    ),
    "page": Blueprint(
        id="page",
        title="HTML page",
        description=(
            "Renders a self-contained HTML page from records and writes it to "
            "disk — something you can send someone."
        ),
        files={ENTRYPOINT: _PAGE_APP},
    ),
}


def blueprint_catalogue() -> str:
    """The blueprint list, as the agent reads it."""
    return "\n".join(
        f"- `{bp.id}` — {bp.title}: {bp.description}"
        for bp in sorted(BLUEPRINTS.values(), key=lambda b: b.id)
    )


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


# ── running ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class AppRunResult:
    ok: bool
    value: Any = None
    stdout: str = ""
    error: str = ""
    exit_code: int | None = 0
    timed_out: bool = False
    env_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "stdout": self.stdout,
            "error": self.error,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "env_calls": self.env_calls,
        }


_RUNNER = '''\
import json, runpy, sys, traceback

_payload = json.loads(sys.stdin.read() or "{}")
_module = runpy.run_path(_payload["entrypoint"])
_run = _module.get("run")
if _run is None:
    print(json.dumps({"__shipit_error__": "app.py does not define run(input, env)"}),
          file=sys.stderr)
    raise SystemExit(2)

try:
    _value = _run(_payload.get("input") or {}, env)
except Exception:
    print(json.dumps({"__shipit_error__": traceback.format_exc(limit=6)}),
          file=sys.stderr)
    raise SystemExit(1)

try:
    _encoded = json.dumps(_value, default=str)
except (TypeError, ValueError):
    _encoded = json.dumps(str(_value))
print("__SHIPIT_APP_RESULT__" + _encoded)
'''


def run_app(
    app: App,
    payload: dict[str, Any] | None = None,
    *,
    invoker: Any = None,
    bindings: dict[str, Any] | None = None,
    timeout_seconds: float = 60.0,
    python: str | None = None,
    cwd: str | Path | None = None,
) -> AppRunResult:
    """Run *app* in a subprocess and return what its ``run()`` returned.

    ``env`` inside the app carries only the bindings the manifest names, and
    every call on it crosses the capability bridge back to the parent's
    permission engine. With no ``invoker`` the app still runs — it simply has
    no `env`, which is the right outcome for an app that never asked for one.
    """
    from shipit_agent.codemode.bridge import BridgeServer
    from shipit_agent.codemode.preamble import build_preamble

    wired = _wired_bindings(app, bindings or {})
    missing = sorted(set(app.manifest.bindings) - set(wired))
    source = build_preamble(wired) + "\n" + _RUNNER

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    bridge: Any = None
    if invoker is not None:
        bridge = BridgeServer(invoker)
        bridge.start()
        child_env.update(bridge.address.as_env())

    try:
        with tempfile.TemporaryDirectory(prefix="shipit-app-") as workdir:
            script = Path(workdir) / "_runner.py"
            script.write_text(source, encoding="utf-8")
            stdin = json.dumps(
                {"entrypoint": str(app.entrypoint), "input": payload or {}}
            )
            try:
                completed = subprocess.run(
                    [python or sys.executable, "-I", str(script)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=str(cwd or app.path),
                    env=child_env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return AppRunResult(
                    ok=False,
                    error=f"app timed out after {timeout_seconds:.0f}s",
                    exit_code=None,
                    timed_out=True,
                )
    finally:
        if bridge is not None:
            bridge.stop()

    result = _parse(completed.stdout, completed.stderr, completed.returncode)
    result.env_calls = bridge.call_count if bridge is not None else 0
    if missing and not result.ok:
        result.error += (
            f"\n(the manifest wires {', '.join(missing)}, which the agent's "
            "environment does not currently offer)"
        )
    return result


def _wired_bindings(app: App, available: dict[str, Any]) -> dict[str, Any]:
    """The app's env: only what its manifest names, under the names it chose."""
    wired: dict[str, Any] = {}
    for inner, outer in app.manifest.bindings.items():
        binding = available.get(outer)
        if binding is not None:
            wired[inner] = binding
    return wired


def _parse(stdout: str, stderr: str, code: int) -> AppRunResult:
    marker = "__SHIPIT_APP_RESULT__"
    value: Any = None
    lines = []
    for line in (stdout or "").splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
            except ValueError:
                value = line[len(marker):]
        else:
            lines.append(line)

    error = ""
    for line in (stderr or "").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            error += line + "\n"
            continue
        if isinstance(payload, dict) and "__shipit_error__" in payload:
            error += str(payload["__shipit_error__"])
        else:
            error += line + "\n"

    return AppRunResult(
        ok=code == 0 and not error.strip(),
        value=value,
        stdout="\n".join(lines).strip(),
        error=error.strip(),
        exit_code=code,
    )
