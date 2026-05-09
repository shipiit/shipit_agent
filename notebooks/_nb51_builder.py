"""Build notebooks/51_support_zendesk_triage.ipynb.

Customer Support persona: search open Zendesk tickets, classify, vision
OCR a customer screenshot attached to a ticket, render a triage
dashboard.

Run ``python notebooks/_nb51_builder.py`` to regenerate the notebook.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "51_support_zendesk_triage.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": text.splitlines(keepends=True),
    }


CELLS: list[dict] = [
    md(
        "# 51 · Customer Support — Zendesk Triage + Vision\n"
        "\n"
        "**Persona:** Customer Support lead. **Tools exercised:** "
        "`ZendeskTool`, `VisionTool`, `DashboardRenderTool`.\n"
        "\n"
        "End-to-end workflow:\n"
        "\n"
        "1. Search open high-priority tickets.\n"
        "2. Classify by reported issue category.\n"
        "3. Vision-read an attached screenshot on one ticket to extract the "
        "error message.\n"
        "4. Render a triage dashboard with counts, blockers, and a verdict.\n"
        "\n"
        "Zendesk calls are stubbed. VisionTool uses whatever LLM you wire — "
        "with `SimpleEchoLLM` you get the request shape; plug in a "
        "vision-capable LLM for real OCR.\n"
    ),
    md("## Setup"),
    code(
        "from pathlib import Path\n"
        "\n"
        "def _find_notebooks_dir() -> Path:\n"
        "    cwd = Path.cwd().resolve()\n"
        "    if cwd.name == 'notebooks':\n"
        "        return cwd\n"
        "    candidate = cwd / 'notebooks'\n"
        "    return candidate if candidate.is_dir() else cwd\n"
        "WORKSPACE = _find_notebooks_dir() / '_support_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    md("## 1 · Pick a model"),
    code(
        "# from shipit_agent.llms import build_llm_from_settings\n"
        "# llm = build_llm_from_settings({'provider': 'bedrock',\n"
        "#     'model': 'bedrock/anthropic.claude-sonnet-4-5-v2:0'}, provider='bedrock')\n"
        "# llm = build_llm_from_settings({'provider': 'litellm',\n"
        "#     'model': 'openai/gpt-4o'}, provider='litellm')\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(model='gpt-4o',\n"
        "#     api_base='https://litellm.internal', api_key='sk-proxy')\n"
        "\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    md("## 2 · Wire up the Zendesk tool with a stub"),
    code(
        "from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore\n"
        "from shipit_agent.tools.zendesk import ZendeskTool\n"
        "\n"
        "store = InMemoryCredentialStore()\n"
        "store.set(CredentialRecord(\n"
        "    key='zendesk', provider='zendesk',\n"
        "    secrets={'token': 'zd-demo', 'email': 'ops@acme.com'},\n"
        "    metadata={'base_url': 'https://acme.zendesk.com',\n"
        "              'auth_scheme': 'Basic'},\n"
        "))\n"
        "zd = ZendeskTool(credential_store=store)\n"
        "\n"
        "_TICKETS = [\n"
        "    {'id': 9001, 'subject': 'Card declined on Pro upgrade', 'status': 'open',\n"
        "     'priority': 'high', 'tags': ['billing', 'card'],\n"
        "     'requester_id': 501, 'screenshot_url': 'https://example.com/zd/ticket-9001.png'},\n"
        "    {'id': 9002, 'subject': 'Dashboard shows 502 after login', 'status': 'open',\n"
        "     'priority': 'urgent', 'tags': ['outage', 'frontend'],\n"
        "     'requester_id': 502},\n"
        "    {'id': 9003, 'subject': 'Invoice PDF export missing VAT line', 'status': 'open',\n"
        "     'priority': 'normal', 'tags': ['billing', 'invoice', 'export'],\n"
        "     'requester_id': 503},\n"
        "    {'id': 9004, 'subject': 'Slack integration disconnects every hour', 'status': 'open',\n"
        "     'priority': 'high', 'tags': ['integrations', 'slack'],\n"
        "     'requester_id': 504},\n"
        "]\n"
        "\n"
        "def _fake_zd(*, record, method, path, query=None, body=None):\n"
        "    if path == '/api/v2/search.json':\n"
        "        return {'results': _TICKETS, 'count': len(_TICKETS)}\n"
        "    if path.startswith('/api/v2/tickets/'):\n"
        "        tid = int(path.rsplit('/', 1)[-1].split('.')[0])\n"
        "        for t in _TICKETS:\n"
        "            if t['id'] == tid:\n"
        "                return {'ticket': t}\n"
        "    return {}\n"
        "\n"
        "zd._request_json = _fake_zd\n"
        "print('zendesk stub installed')\n"
    ),
    md("## 3 · Search open high-priority tickets"),
    code(
        "from shipit_agent.tools.base import ToolContext\n"
        "\n"
        "ctx = ToolContext(prompt='support triage', state={'credential_store': store})\n"
        "\n"
        "tickets_out = zd.run(ctx, action='search_tickets',\n"
        "                       query='status:open priority>=high')\n"
        "print(tickets_out.text)\n"
        "tickets = tickets_out.metadata.get('items') or []\n"
    ),
    md("## 4 · Classify by tag-derived category"),
    code(
        "from collections import Counter\n"
        "\n"
        "def categorize(tags):\n"
        "    for t in tags:\n"
        "        if t in ('billing', 'invoice'): return 'Billing'\n"
        "        if t in ('outage', 'frontend', 'backend'): return 'Reliability'\n"
        "        if t in ('integrations', 'slack', 'webhook'): return 'Integrations'\n"
        "    return 'Other'\n"
        "\n"
        "counts = Counter(categorize(t.get('tags', [])) for t in tickets)\n"
        "for cat, n in counts.most_common():\n"
        "    print(f'{cat:<14} {n}')\n"
    ),
    md(
        "## 5 · Vision pass on the screenshot from ticket 9001\n"
        "\n"
        "One ticket has a customer screenshot attached. We ask the vision "
        "tool to read the on-screen error text and summarise it.\n"
    ),
    code(
        "from shipit_agent.tools.vision import VisionTool\n"
        "\n"
        "vision = VisionTool(llm=llm)\n"
        "target = next(t for t in tickets if t.get('screenshot_url'))\n"
        "v = vision.run(ctx, image=target['screenshot_url'],\n"
        "                prompt='Extract the exact error message shown on the screen.')\n"
        "print(f\"ticket #{target['id']}\")\n"
        "print(f\"vision text: {v.text[:240]}\")\n"
    ),
    md("## 6 · Triage dashboard"),
    code(
        "from shipit_agent.tools.dashboard_render import DashboardRenderTool\n"
        "\n"
        "dash = DashboardRenderTool(workspace_root=WORKSPACE)\n"
        "\n"
        "metric_items = [\n"
        "    {'label': 'Open tickets', 'value': str(len(tickets))},\n"
        "    {'label': 'Urgent', 'value': str(sum(1 for t in tickets if t.get('priority') == 'urgent'))},\n"
        "    {'label': 'High', 'value': str(sum(1 for t in tickets if t.get('priority') == 'high'))},\n"
        "]\n"
        "\n"
        "palette = ['#d85a30', '#185fa5', '#534ab7', '#888888']\n"
        "bars = [\n"
        "    {'label': cat, 'pct': int(round(n / max(1, len(tickets)) * 100)),\n"
        "     'color': palette[i % len(palette)]}\n"
        "    for i, (cat, n) in enumerate(counts.most_common())\n"
        "]\n"
        "\n"
        "timeline = [\n"
        "    {'period': f'#{t[\"id\"]}', 'head': t['subject'],\n"
        "     'desc': f\"priority={t['priority']} tags={','.join(t['tags'])}\",\n"
        "     'dot_color': '#d85a30' if t['priority'] == 'urgent' else '#185fa5',\n"
        "     'tags': [{'text': t['priority'], 'color': 'red' if t['priority']=='urgent' else 'blue'}]}\n"
        "    for t in tickets\n"
        "]\n"
        "\n"
        "result = dash.run(\n"
        "    ToolContext(prompt='support triage',\n"
        "                 state={'artifact_workspace_root': str(WORKSPACE)}),\n"
        "    title='Support Triage — 2026-04-24',\n"
        "    subtitle='Open tickets, priority>=high',\n"
        "    lang='en',\n"
        "    sections=[\n"
        "        {'type': 'metrics', 'title': 'Queue', 'columns': 3, 'items': metric_items},\n"
        "        {'type': 'bars', 'title': 'By category', 'items': bars},\n"
        "        {'type': 'timeline', 'title': 'Open ticket queue', 'items': timeline},\n"
        "        {'type': 'verdict', 'title': 'Triage verdict',\n"
        "         'text': ('**Reliability is the breakout category.** One urgent 502 '\n"
        "                  'needs an on-call page; billing churn is steady.')},\n"
        "    ],\n"
        "    export=True,\n"
        ")\n"
        "print(result.text)\n"
        "print('artifact path:', result.metadata.get('path'))\n"
    ),
    md(
        "## Next steps\n"
        "\n"
        "* See `docs-app/content/source/tools/zendesk.md` for the full Zendesk "
        "action surface (macros, comments, assignment).\n"
        "* Pair with a `VerifierTool` + autopilot loop so tickets are "
        "auto-triaged and routed to the right squad every 5 minutes.\n"
    ),
]


def main() -> None:
    notebook = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for i, cell in enumerate(notebook["cells"]):
        cell.setdefault("id", f"cell-{i:02d}")
    OUT.write_text(json.dumps(notebook, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
