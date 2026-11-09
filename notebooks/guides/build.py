"""Build (and run) the in-depth guide notebooks from their sources in src/.

    .venv/bin/python notebooks/guides/build.py            # every guide
    .venv/bin/python notebooks/guides/build.py g01 g03    # some
    .venv/bin/python notebooks/guides/build.py --no-run   # write cells only (new guides)

Each src/gNN_*.py defines TITLE and CELLS, a list of md(...) and code(...).
Running executes the notebook from this folder, so build_llm_from_env() finds
the repo's .env, then scrubs home paths and the user name from the outputs.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import importlib.util
import re
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 300


#: Real addresses never reach a saved output; example domains stay readable.
_EMAIL = re.compile(r"[\w.+-]+@(?!example\.(?:com|org|net)\b)[\w-]+(?:\.[\w-]+)+")


def git_user_name() -> str:
    """The committer name on this machine, so saved outputs never show it."""
    try:
        name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return name


GIT_NAME = git_user_name()


#: The repository's own folder: outputs show it as <repo>, not the machine's layout.
REPO = HERE.parents[1]


def _scrub(text: str) -> str:
    for form in (str(REPO), os.path.realpath(REPO), str(REPO).replace(str(Path.home()), "~", 1)):
        text = text.replace(form, "<repo>")
    text = _EMAIL.sub("[email]", text)
    if GIT_NAME:
        text = text.replace(GIT_NAME, "you")
    text = re.sub(r"/(Users|home)/[^/\s\"']+", "~", text)
    text = re.sub(r"/(private/)?var/folders/[^\s\"']+", "/tmp", text)
    return text.replace(getpass.getuser(), "you")


#: Notices the provider SDKs print to stderr that say nothing about the guide.
_NOISE = ("takes precedence over the SDK's profile",)
#: stderr blocks that are library shutdown noise, dropped whole.
_NOISE_BLOCKS = ("Exception ignored while calling deallocator",)


def _scrub_outputs(nb: nbformat.NotebookNode) -> None:
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            if out.get("name") == "stderr" and any(n in out["text"] for n in _NOISE_BLOCKS):
                out["text"] = ""
            if out.get("name") == "stderr":
                out["text"] = "".join(line for line in out["text"].splitlines(keepends=True) if not any(n in line for n in _NOISE))
            if "text" in out:
                out["text"] = _scrub(out["text"])
            for key, value in list(out.get("data", {}).items()):
                if isinstance(value, str):
                    out["data"][key] = _scrub(value)
        cell["outputs"] = [o for o in cell.get("outputs", []) if o.get("output_type") != "stream" or o["text"].strip()]


def _load(path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(source: Path, run: bool) -> Path:
    module = _load(source)
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    for kind, text in module.CELLS:
        nb.cells.append(nbformat.v4.new_markdown_cell(text) if kind == "md" else nbformat.v4.new_code_cell(text))
    if run:
        NotebookClient(nb, timeout=TIMEOUT_SECONDS, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}).execute()
        _scrub_outputs(nb)
    target = HERE / f"{source.stem[1:]}.ipynb"
    if not run and target.exists():
        raise SystemExit(f"{target.name} already has run outputs; build it with the run to replace it")
    nbformat.write(nb, target)
    return target


def main(argv: list[str]) -> None:
    run = "--no-run" not in argv
    wanted = [a for a in argv if not a.startswith("--")]
    for source in sorted((HERE / "src").glob("g[0-9][0-9]_*.py")):
        if wanted and not any(source.stem.startswith(w) for w in wanted):
            continue
        print("built", build(source, run).name)


if __name__ == "__main__":
    main(sys.argv[1:])
