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

from .blueprints import BLUEPRINTS
from .blueprints import blueprint_catalogue as blueprint_catalogue
from .models import ENTRYPOINT as ENTRYPOINT
from .models import App, AppManifest, Blueprint
from .models import validate_name as validate_name
from .runner import AppRunResult, run_app
from .store import MANIFEST as MANIFEST
from .store import AppStore, app_docstring

__all__ = [
    "App",
    "app_docstring",
    "AppManifest",
    "AppRunResult",
    "AppStore",
    "BLUEPRINTS",
    "Blueprint",
    "run_app",
]


# ── running ──────────────────────────────────────────────────────────────
