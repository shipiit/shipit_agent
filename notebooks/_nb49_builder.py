"""Build notebooks/49_sales_lead_enrichment.ipynb.

Sales persona: enrich a new lead via LinkedIn, check for prior Gmail
threads, draft outreach, log a Salesforce activity.

Run ``python notebooks/_nb49_builder.py`` to regenerate the notebook.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "49_sales_lead_enrichment.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
    }


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
        "# 49 · Sales — Lead Enrichment → Outreach → Salesforce Activity\n"
        "\n"
        "**Persona:** Sales. **Tools exercised:** `SalesforceTool`, "
        "`LinkedInSearchTool`, `GmailTool`.\n"
        "\n"
        "End-to-end workflow:\n"
        "\n"
        "1. Receive a new lead (name, company, email).\n"
        "2. Enrich with a LinkedIn profile lookup (read-only).\n"
        "3. Check Gmail for any prior thread with this contact.\n"
        "4. Draft a personalized outreach message.\n"
        "5. Log the touchpoint as a Salesforce Task.\n"
        "\n"
        "All three external tools are stubbed so the notebook runs clean "
        "without credentials. LinkedInSearchTool is deliberately read-only — "
        "it cannot send messages or connection requests even if you try.\n"
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
        "WORKSPACE = _find_notebooks_dir() / '_sales_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    md("## 1 · Pick a model"),
    code(
        "# from shipit_agent.llms import build_llm_from_settings\n"
        "# llm = build_llm_from_settings({'provider': 'bedrock',\n"
        "#     'model': 'bedrock/anthropic.claude-sonnet-4-5-v2:0'}, provider='bedrock')\n"
        "# llm = build_llm_from_settings({'provider': 'litellm',\n"
        "#     'model': 'openai/gpt-4o-mini'}, provider='litellm')\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(model='gpt-4o-mini',\n"
        "#     api_base='https://litellm.internal', api_key='sk-proxy')\n"
        "\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    md(
        "## 2 · Wire up credential records + stubbed tools\n"
        "\n"
        "Salesforce needs a `base_url` (the org's instance URL) in the "
        "credential record — otherwise the tool returns `missing_instance_url` "
        "before any stub gets a chance to run. LinkedIn similarly needs "
        "`base_url`. Gmail uses `google-api-python-client` under the hood, not "
        "the HTTP connector base, so we override `.run` directly with a canned "
        "response.\n"
    ),
    code(
        "from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore\n"
        "from shipit_agent.tools.base import ToolContext, ToolOutput\n"
        "from shipit_agent.tools.salesforce import SalesforceTool\n"
        "from shipit_agent.tools.linkedin import LinkedInSearchTool\n"
        "from shipit_agent.tools.gmail import GmailTool\n"
        "\n"
        "store = InMemoryCredentialStore()\n"
        "store.set(CredentialRecord(\n"
        "    key='salesforce', provider='salesforce',\n"
        "    secrets={'token': 'sf-demo'},\n"
        "    metadata={'base_url': 'https://acme.my.salesforce.com'},\n"
        "))\n"
        "store.set(CredentialRecord(\n"
        "    key='linkedin', provider='linkedin',\n"
        "    secrets={'token': 'li-demo'},\n"
        "    metadata={'base_url': 'https://nubela.co/proxycurl/api',\n"
        "              'auth_mode': 'bearer'},\n"
        "))\n"
        "store.set(CredentialRecord(\n"
        "    key='gmail', provider='gmail',\n"
        "    secrets={'token': 'gmail-demo'},\n"
        "))\n"
        "\n"
        "sf = SalesforceTool(credential_store=store, allow_writes=True)\n"
        "li = LinkedInSearchTool(credential_store=store)\n"
        "gm = GmailTool(credential_store=store)\n"
        "\n"
        "# ---- Salesforce stub --------------------------------------------\n"
        "def _fake_sf(*, record, method, path, query=None, body=None):\n"
        "    if '/sobjects/Task' in path and method.upper() == 'POST':\n"
        "        return {'id': '00T5f000001abcdEAA', 'success': True}\n"
        "    if path.endswith('/query'):\n"
        "        return {'totalSize': 0, 'done': True, 'records': []}\n"
        "    return {}\n"
        "sf._request_json = _fake_sf\n"
        "\n"
        "# ---- LinkedIn stub ----------------------------------------------\n"
        "def _fake_linkedin(*, record, method, path, query=None, body=None):\n"
        "    return {\n"
        "        'full_name': 'Priya Menon',\n"
        "        'headline': 'VP Engineering at Northwind Cloud',\n"
        "        'company': 'Northwind Cloud',\n"
        "        'location': 'London, United Kingdom',\n"
        "        'experience': [\n"
        "            {'company': 'Northwind Cloud', 'title': 'VP Engineering',\n"
        "             'from': '2023-01', 'to': 'present'},\n"
        "            {'company': 'Stripe', 'title': 'Eng Manager',\n"
        "             'from': '2019-04', 'to': '2022-12'},\n"
        "        ],\n"
        "    }\n"
        "li._request_json = _fake_linkedin\n"
        "\n"
        "# ---- Gmail stub (google-api based — override .run directly) -----\n"
        "def _fake_gmail_run(context, **kwargs):\n"
        "    # Demo-only: pretend no prior thread exists for this contact.\n"
        "    return ToolOutput(\n"
        "        text='No Gmail messages found for: priya.menon@northwind.cloud',\n"
        "        metadata={'provider': 'gmail', 'connected': True,\n"
        "                  'action': 'search', 'count': 0, 'items': []},\n"
        "    )\n"
        "gm.run = _fake_gmail_run  # type: ignore[assignment]\n"
        "print('tools ready:', sf.name, li.name, gm.name)\n"
    ),
    md(
        "## 3 · The new lead\n"
        "\n"
        "A marketing-qualified lead just landed. We have a name, email, and "
        "LinkedIn URL — nothing else yet.\n"
    ),
    code(
        "lead = {\n"
        "    'name': 'Priya Menon',\n"
        "    'email': 'priya.menon@northwind.cloud',\n"
        "    'linkedin_url': 'https://www.linkedin.com/in/priyamenon',\n"
        "    'company': 'Northwind Cloud',\n"
        "}\n"
        "print(lead)\n"
    ),
    md("## 4 · Enrich via LinkedIn (read-only)"),
    code(
        "ctx = ToolContext(prompt='lead enrichment', state={'credential_store': store})\n"
        "\n"
        "li_out = li.run(ctx, action='lookup_profile', profile_url=lead['linkedin_url'])\n"
        "print(li_out.text)\n"
        "profile = li_out.metadata.get('item') or li_out.metadata.get('profile') or {}\n"
        "# Fall back to the raw stub payload shape — the tool formats it into\n"
        "# `item`/`profile` depending on the upstream vendor.\n"
        "profile = profile or _fake_linkedin(record=None, method='GET', path='/', query=None, body=None)\n"
        "print()\n"
        "print('headline:', profile.get('headline'))\n"
        "print('location:', profile.get('location'))\n"
    ),
    md("## 5 · Check Gmail for prior correspondence"),
    code(
        "gmail_out = gm.run(ctx, action='search',\n"
        "                    query=f'from:{lead[\"email\"]} OR to:{lead[\"email\"]}')\n"
        "print(gmail_out.text)\n"
        "has_prior_thread = bool(gmail_out.metadata.get('count', 0))\n"
        "print('has_prior_thread:', has_prior_thread)\n"
    ),
    md(
        "## 6 · Draft personalized outreach\n"
        "\n"
        "In a real run you'd call the LLM to draft the email — here we just "
        "template it from the enrichment data so the notebook is deterministic "
        "without external model calls.\n"
    ),
    code(
        "subject = f'{lead[\"company\"]} engineering scaling — quick question'\n"
        "body = (\n"
        "    f\"Hi {lead['name'].split()[0]},\\n\\n\"\n"
        "    f\"Saw you're VP Eng at {lead['company']}. Given your Stripe \"\n"
        "    f\"background, curious how you're thinking about agent \"\n"
        "    f\"orchestration as your team scales.\\n\\n\"\n"
        "    f\"Would a 15-min call next week be useful? We just shipped \"\n"
        "    f\"shipit-agent v1.0.7 — fan-out + budget-gated long runs.\\n\\n\"\n"
        "    f\"— Rahul\"\n"
        ")\n"
        "print('Subject:', subject)\n"
        "print()\n"
        "print(body)\n"
    ),
    md(
        "## 7 · Log the touchpoint as a Salesforce Task\n"
        "\n"
        "`log_activity` is always allowed on `SalesforceTool` — other writes are "
        "gated by `allow_writes=True`.\n"
    ),
    code(
        "sf_out = sf.run(ctx, action='log_activity',\n"
        "                 subject=subject,\n"
        "                 description=body,\n"
        "                 related_to_id='001xx000003DHPiAAO')\n"
        "print(sf_out.text)\n"
        "print('task id:', sf_out.metadata.get('id'))\n"
    ),
    md(
        "## Next steps\n"
        "\n"
        "* LinkedIn tool is **read-only by design** — see "
        "`docs-app/content/source/tools/linkedin.md` for the exact boundary.\n"
        "* For real Salesforce wiring see "
        "`docs-app/content/source/tools/salesforce.md` — OAuth instance URL + "
        "session token.\n"
        "* Drive this flow with `Autopilot(..., goal=Goal('Enrich new leads '\n"
        "'from inbound form'))` on a 15-minute cron.\n"
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
