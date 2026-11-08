"""The blueprint catalogue apps are created from."""

from __future__ import annotations

from .blueprint_basic import _PAGE_APP, _REPORT_APP, _TABLE_APP
from .blueprint_dashboard import _DASHBOARD_APP
from .blueprint_sheet import _SHEET_APP
from .blueprint_workflow import _WORKFLOW_APP
from .models import ENTRYPOINT, Blueprint

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
    "dashboard": Blueprint(
        id="dashboard",
        title="Dashboard",
        description=(
            "Headline numbers and a bar chart from records — the thing you "
            "send someone who asked where revenue landed."
        ),
        files={ENTRYPOINT: _DASHBOARD_APP},
    ),
    "sheet": Blueprint(
        id="sheet",
        title="Spreadsheet",
        description=(
            "Records as a spreadsheet: column letters, row numbers, a frozen "
            "header, and cells you can flag."
        ),
        files={ENTRYPOINT: _SHEET_APP},
    ),
    "workflow": Blueprint(
        id="workflow",
        title="Workflow diagram",
        description=(
            "A pipeline as boxes and connectors, with the agent step marked "
            "and a live log underneath."
        ),
        files={ENTRYPOINT: _WORKFLOW_APP},
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

