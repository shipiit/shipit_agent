"""The license is declared as an SPDX expression (PEP 639).

setuptools stops accepting the old ``license = {text = ...}`` table after
2027-02-18, and PEP 639 tools reject a license expression next to a
``License ::`` classifier.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_license_is_an_spdx_expression_with_its_file() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = config["project"]
    assert project["license"] == "MIT"
    assert all((ROOT / name).is_file() for name in project["license-files"])
    assert not [c for c in project["classifiers"] if c.startswith("License ::")]
    assert "setuptools>=77" in config["build-system"]["requires"]
