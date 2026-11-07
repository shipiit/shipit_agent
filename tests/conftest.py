from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _no_ambient_model_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test defaults, not whatever model a developer's ``.env`` names.

    ``import litellm`` loads a ``.env`` found above its install folder, so a
    shared virtualenv inside a checkout puts that checkout's model choices
    into ``os.environ``. Tests that need one set it themselves.
    """
    for name in list(os.environ):
        if name.startswith("SHIPIT_") and name.endswith("_MODEL"):
            monkeypatch.delenv(name)
