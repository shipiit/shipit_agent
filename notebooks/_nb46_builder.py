"""Build notebooks/46_dashboard_render_tool_and_litellm.ipynb.

Run ``python notebooks/_nb46_builder.py`` to regenerate the notebook
after any edits here. Kept as a script (not run-on-import) so the
notebook JSON can be diff-reviewed in pull requests.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "46_dashboard_render_tool_and_litellm.ipynb"


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
        "# 46 · Dashboard Render Tool + LiteLLM\n"
        "\n"
        "This notebook shows three things end-to-end:\n"
        "\n"
        "1. How an **Agent** drives the `DashboardRenderTool` to produce a rich, "
        "self-contained HTML dashboard (metrics, timeline, cards, phases, chart, verdict).\n"
        "2. How to plug in **any model via LiteLLM** — either directly (`LiteLLMChatLLM`) "
        "or through a self-hosted **LiteLLM proxy** (`LiteLLMProxyChatLLM`). Companies that "
        "already run LiteLLM for routing, rate-limiting, or cost tracking can point the "
        "whole `shipit_agent` stack at their proxy without touching adapter code.\n"
        "3. How **Autopilot** automatically surfaces the rendered HTML as an artifact via "
        "`ArtifactCollector.ingest_tool_metadata` — no glue code.\n"
    ),
    # ── setup ──────────────────────────────────────────────────────
    md("## Setup"),
    code(
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        "# Resolve a notebook-local workspace whether this notebook is run\n"
        "# from the repo root (`jupyter lab`) or from `notebooks/`.\n"
        "# Put exports under notebooks/_dashboard_workspace either way.\n"
        "def _find_notebooks_dir() -> Path:\n"
        "    cwd = Path.cwd().resolve()\n"
        "    if cwd.name == 'notebooks':\n"
        "        return cwd\n"
        "    candidate = cwd / 'notebooks'\n"
        "    return candidate if candidate.is_dir() else cwd\n"
        "WORKSPACE = _find_notebooks_dir() / '_dashboard_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    # ── section 1: pick a model ────────────────────────────────────
    md(
        "## 1 · Pick a model\n"
        "\n"
        "`build_llm_from_settings` resolves a provider from the `provider` key. All the "
        "settings listed below can alternatively be set via environment variables "
        "(`SHIPIT_LLM_PROVIDER`, `SHIPIT_LITELLM_MODEL`, `SHIPIT_LITELLM_API_BASE`, etc.) — "
        "whichever is more convenient for your deployment.\n"
        "\n"
        "### Bring your own LiteLLM (URL + key)\n"
        "If your company already runs a LiteLLM proxy, point every shipit_agent "
        "Agent / Autopilot / crew at it with three fields:\n"
        "\n"
        "| Field | What it is |\n"
        "| --- | --- |\n"
        "| `api_base` | Your LiteLLM proxy URL, e.g. `https://litellm.acme.com` |\n"
        "| `api_key` | Bearer token your proxy accepts |\n"
        "| `model` | Whatever model alias the proxy routes — `gpt-4o-mini`, `claude-sonnet-4-5`, … |\n"
        "\n"
        "The proxy handles credentials for upstream providers, rate-limiting, "
        "cost tracking, and routing — shipit_agent just speaks OpenAI-compatible "
        "HTTP to it.\n"
    ),
    code(
        "from shipit_agent.llms import build_llm_from_settings\n"
        "\n"
        "# --- Option A: AWS Bedrock (default provider) -----------------\n"
        "# Needs AWS credentials and AWS_REGION_NAME.\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'bedrock',\n"
        "#     'model': 'bedrock/openai.gpt-oss-120b-1:0',\n"
        "# }, provider='bedrock')\n"
        "\n"
        "# --- Option B: LiteLLM direct — any LiteLLM-supported model ---\n"
        "# Examples: 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-4-5',\n"
        "# 'groq/llama-3.3-70b-versatile', 'ollama/llama3.1', etc.\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'litellm',\n"
        "#     'model': 'openai/gpt-4o-mini',\n"
        "#     'api_key': os.environ.get('OPENAI_API_KEY'),\n"
        "# }, provider='litellm')\n"
        "\n"
        "# --- Option C: LiteLLM proxy (your URL + your key) -----------\n"
        "# For companies running `litellm --config` as a central gateway.\n"
        "# Two equivalent ways to wire it:\n"
        "#\n"
        "# C1. Factory path (declarative — good for env-driven configs):\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'litellm',\n"
        "#     'model': 'gpt-4o-mini',                        # alias your proxy routes\n"
        "#     'api_base': 'https://litellm.my-company.internal',\n"
        "#     'api_key': os.environ.get('MY_LITELLM_PROXY_TOKEN'),\n"
        "#     'custom_llm_provider': 'openai',               # proxy speaks OpenAI format\n"
        "# }, provider='litellm')\n"
        "#\n"
        "# C2. Direct class (imperative — explicit about what gets constructed):\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(\n"
        "#     model='gpt-4o-mini',\n"
        "#     api_base='https://litellm.my-company.internal',\n"
        "#     api_key='sk-proxy-token',\n"
        "# )\n"
        "#\n"
        "# Env-var shortcut: set SHIPIT_LITELLM_MODEL / SHIPIT_LITELLM_API_BASE /\n"
        "# SHIPIT_LITELLM_API_KEY, then just call build_llm_from_settings(provider='litellm').\n"
        "\n"
        "# For a notebook that runs without creds, use the deterministic echo model.\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    # ── section 2: render_dashboard directly ───────────────────────
    md(
        "## 2 · Render a dashboard directly (no LLM)\n"
        "\n"
        "The renderer is pure-Python and works standalone. You build a "
        "spec dict, call `render_dashboard(spec)`, and get back a "
        "single self-contained HTML document (inline CSS, Chart.js via "
        "CDN only when a chart section is present).\n"
    ),
    code(
        "from shipit_agent.tools.dashboard_render import render_dashboard\n"
        "\n"
        "spec = {\n"
        "    'title': 'Rahul — Complete Life Vision 2026–2035',\n"
        "    'subtitle': 'Kundli + Hast Rekha · Venus dasha · April 2026',\n"
        "    'lang': 'hi',\n"
        "    'sections': [\n"
        "        {'type': 'metrics', 'title': 'Life Snapshot', 'columns': 4, 'items': [\n"
        "            {'label': 'उम्र', 'value': '30', 'sub': 'Best phase ahead'},\n"
        "            {'label': 'दशा', 'value': 'शुक्र', 'sub': '2043 तक'},\n"
        "            {'label': 'Ventures', 'value': '4', 'sub': 'ShipIt primary'},\n"
        "            {'label': 'साढ़ेसाती', 'value': 'Peak',\n"
        "             'sub': 'ends June 2027', 'color': '#ba7517'},\n"
        "        ]},\n"
        "        {'type': 'line_chart', 'title': 'Income growth 2026–2035',\n"
        "         'labels': [str(y) for y in range(2026, 2036)],\n"
        "         'values': [20, 35, 55, 70, 85, 95, 110, 140, 165, 190],\n"
        "         'color': '#185fa5'},\n"
        "        {'type': 'bars', 'title': 'Income sources', 'items': [\n"
        "            {'label': 'Enterprise licensing', 'pct': 88, 'color': '#185fa5'},\n"
        "            {'label': 'SaaS subscriptions',   'pct': 75, 'color': '#1d9e75'},\n"
        "            {'label': 'Cloud hosted product', 'pct': 65, 'color': '#534ab7'},\n"
        "            {'label': 'Courses / training',   'pct': 50, 'color': '#ba7517'},\n"
        "            {'label': 'Consulting',           'pct': 38, 'color': '#888888'},\n"
        "        ]},\n"
        "        {'type': 'timeline', 'title': 'Love life timeline', 'items': [\n"
        "            {'period': 'April 2026', 'head': 'Internal transformation',\n"
        "             'desc': 'Jupiter lagna. Aura improving. Prep phase.',\n"
        "             'dot_color': '#888888',\n"
        "             'tags': [{'text': 'Prep', 'color': 'amber'}]},\n"
        "            {'period': 'Jun–Jul 2026', 'head': 'PEAK WINDOW',\n"
        "             'desc': 'Significant connection. Friendship → romance.',\n"
        "             'dot_color': '#185fa5',\n"
        "             'tags': [{'text': 'Peak', 'color': 'blue'},\n"
        "                      {'text': 'She arrives', 'color': 'blue'}]},\n"
        "            {'period': '2027–2028', 'head': 'Marriage',\n"
        "             'desc': 'Sadhesati khatam. Shaadi ki baat family tak.',\n"
        "             'dot_color': '#1d9e75',\n"
        "             'tags': [{'text': 'Shaadi', 'color': 'green'}]},\n"
        "        ]},\n"
        "        {'type': 'cards', 'title': 'Future partner', 'columns': 2, 'cards': [\n"
        "            {'title': 'Physical appearance', 'rows': [\n"
        "                {'strong': 'Eyes:', 'text': 'Deep, expressive, magnetic.',\n"
        "                 'dot_color': '#185fa5'},\n"
        "                {'strong': 'Height:', 'text': '5\\'4\\\" – 5\\'7\\\".',\n"
        "                 'dot_color': '#185fa5'},\n"
        "                {'strong': 'Style:', 'text': 'Minimal, tasteful.',\n"
        "                 'dot_color': '#185fa5'},\n"
        "            ]},\n"
        "            {'title': 'Personality', 'rows': [\n"
        "                {'strong': 'First:', 'text': 'Reserved, observant.',\n"
        "                 'dot_color': '#1d9e75'},\n"
        "                {'strong': 'Intelligence:', 'text': 'High — matches yours.',\n"
        "                 'dot_color': '#1d9e75'},\n"
        "                {'strong': 'Love style:', 'text': 'Acts of service.',\n"
        "                 'dot_color': '#1d9e75'},\n"
        "            ]},\n"
        "        ]},\n"
        "        {'type': 'lifestyle_grid', 'title': 'Future lifestyle 2026–2035', 'items': [\n"
        "            {'icon': '🏠', 'title': 'Housing — 2027', 'desc': 'Better Warsaw apartment.'},\n"
        "            {'icon': '🚗', 'title': 'Car — 2027–28', 'desc': 'Reliable, utility-focused.'},\n"
        "            {'icon': '✈️', 'title': 'Travel', 'desc': 'Europe + international.'},\n"
        "            {'icon': '💍', 'title': 'Marriage', 'desc': 'Meaningful ceremony.'},\n"
        "            {'icon': '👶', 'title': 'Children — 2029–31', 'desc': 'One child strong yoga.'},\n"
        "            {'icon': '🌍', 'title': 'Global — 2030+', 'desc': 'Financial freedom.'},\n"
        "        ]},\n"
        "        {'type': 'phases', 'title': 'Life phases — year by year', 'items': [\n"
        "            {'year': '2026 — Foundation', 'sub': 'Venus–Venus → Venus–Sun',\n"
        "             'items': 'ShipIt PH · Pro tier · First enterprise · Love May–Aug · 3–5x income',\n"
        "             'color': '#ba7517'},\n"
        "            {'year': '2027 — Transition', 'sub': 'Sadhesati ends',\n"
        "             'items': 'MRR stable · Marriage discussions · Team 3–5 · Intl clients',\n"
        "             'color': '#185fa5'},\n"
        "            {'year': '2028 — Milestone', 'sub': 'Venus–Moon → Venus–Mars',\n"
        "             'items': 'Marriage · 1000+ users · Property plan · Seed funding possible',\n"
        "             'color': '#1d9e75'},\n"
        "            {'year': '2030–33 — BREAKTHROUGH', 'sub': 'Venus–Rahu · explosive',\n"
        "             'items': 'Sudden rise · Acquisition offer · Major funding · ShipIt standard',\n"
        "             'color': '#d85a30'},\n"
        "        ]},\n"
        "        {'type': 'bars', 'title': 'Overall life score', 'items': [\n"
        "            {'label': 'Career potential',  'pct': 92, 'color': '#185fa5'},\n"
        "            {'label': 'Financial success', 'pct': 88, 'color': '#1d9e75'},\n"
        "            {'label': 'Marriage happiness','pct': 85, 'color': '#534ab7'},\n"
        "            {'label': 'Fame & recognition','pct': 80, 'color': '#ba7517'},\n"
        "            {'label': 'Family happiness',  'pct': 82, 'color': '#1d9e75'},\n"
        "            {'label': 'International reach','pct': 75, 'color': '#d85a30'},\n"
        "        ]},\n"
        "        {'type': 'verdict', 'title': 'Final verdict',\n"
        "         'text': ('Tum ek **self-made extraordinary journey** par ho. '\n"
        "                  'June–August 2026 turning point hai. **2027–2028 shaadi, '\n"
        "                  '2028–2030 financial freedom, 2030–2033 breakthrough.** '\n"
        "                  'Tumhara best chapter abhi likhna baaki hai. 🌟')},\n"
        "    ],\n"
        "}\n"
        "\n"
        "html_doc = render_dashboard(spec)\n"
        "out_path = WORKSPACE / 'life_vision.html'\n"
        "out_path.write_text(html_doc, encoding='utf-8')\n"
        "print(f'wrote {out_path} — {len(html_doc):,} chars, {len(spec[\"sections\"])} sections')\n"
    ),
    # ── section 3: agent drives the tool ───────────────────────────
    md(
        "## 3 · Agent drives the tool\n"
        "\n"
        "The `DashboardRenderTool` exposes a JSON-schema function that any "
        "Agent can call. A model that's been handed this tool and a user "
        'prompt like _"show me my finance future as a dashboard"_ will '
        "call it with the right spec shape.\n"
        "\n"
        "With `SimpleEchoLLM` as the model the agent won't actually invoke "
        "the tool (echo models don't emit tool calls), but the construction "
        "still verifies the wiring. Swap to a real LLM above to see it call "
        "`render_dashboard` on its own.\n"
    ),
    code(
        "from shipit_agent import Agent\n"
        "from shipit_agent.tools.dashboard_render import DashboardRenderTool\n"
        "\n"
        "dash_tool = DashboardRenderTool(workspace_root=WORKSPACE)\n"
        "agent = Agent(\n"
        "    llm=llm,\n"
        "    prompt=(\n"
        "        'You are a life-planning assistant. When the user asks for a '\n"
        "        'visual dashboard, call render_dashboard with a well-structured spec.'\n"
        "    ),\n"
        "    tools=[dash_tool],\n"
        "    max_iterations=4,\n"
        "    name='life-dashboard-agent',\n"
        ")\n"
        "print(f'tools available: {[t.name for t in agent.tools]}')\n"
    ),
    code(
        "# Directly call the tool the way an LLM would — a round-trip through\n"
        "# the ToolContext / ToolOutput layer mirrors exactly what an Agent does\n"
        "# when its model emits a tool call.\n"
        "from shipit_agent.tools.base import ToolContext\n"
        "\n"
        "out = dash_tool.run(\n"
        "    ToolContext(prompt='demo', state={'artifact_workspace_root': str(WORKSPACE)}),\n"
        "    title='Finance One-Pager — FY26',\n"
        "    subtitle='Dashboard rendered via the agent tool path',\n"
        "    lang='en',\n"
        "    sections=[\n"
        "        {'type': 'metrics', 'title': 'Q2 KPIs', 'columns': 3, 'items': [\n"
        "            {'label': 'MRR', 'value': '$12.4k', 'sub': '+22% QoQ'},\n"
        "            {'label': 'CAC', 'value': '$89', 'sub': '-8%'},\n"
        "            {'label': 'LTV', 'value': '$720', 'sub': 'payback 4.2mo'},\n"
        "        ]},\n"
        "        {'type': 'line_chart', 'title': 'Revenue 2025–2026',\n"
        "         'labels': ['Q1-25','Q2-25','Q3-25','Q4-25','Q1-26','Q2-26'],\n"
        "         'values': [4.2, 5.8, 7.5, 9.1, 10.2, 12.4],\n"
        "         'color': '#1d9e75'},\n"
        "        {'type': 'verdict', 'title': 'Takeaway',\n"
        "         'text': 'Solid **2.5x YoY**. Focus Q3 on **retention**, not new acquisition.'},\n"
        "    ],\n"
        "    export=True,\n"
        ")\n"
        "print(out.text)\n"
        "print('path:', out.metadata.get('path'))\n"
    ),
    # ── section 4: autopilot picks it up ───────────────────────────
    md(
        "## 4 · Autopilot surfaces it as an artifact automatically\n"
        "\n"
        "`ArtifactCollector.ingest_tool_metadata` understands the same "
        "`{'artifact': True, 'kind', 'name', 'content'}` envelope the tool "
        "emits — so an Autopilot run wired with `artifacts=True` captures "
        "the rendered HTML without any integration code.\n"
    ),
    code(
        "from shipit_agent.autopilot import ArtifactCollector\n"
        "\n"
        "collector = ArtifactCollector()\n"
        "collector.ingest_tool_metadata(out.metadata, iteration=1)\n"
        "\n"
        "for a in collector.all():\n"
        "    print(f'{a.kind:<6} {a.name:<30} {len(a.content):>6,} chars')\n"
    ),
    # ── closing ───────────────────────────────────────────────────
    md(
        "## Where to go next\n"
        "\n"
        "* Run this notebook with a real model (Bedrock, LiteLLM, LiteLLM-proxy, OpenAI, "
        "Anthropic) by uncommenting one of the LLM builders in Section 1.\n"
        "* Wrap the agent in `Autopilot(..., goal=Goal('Build a finance dashboard'), "
        "tools=[DashboardRenderTool(), ...], artifacts=True)` for a long-running job that "
        "produces a dashboard at the end.\n"
        "* For arbitrary providers, LiteLLM already supports 100+ model endpoints — any "
        "string LiteLLM accepts for `model=` works with `LiteLLMChatLLM`.\n"
        "* To centralise routing / rate-limiting, run `litellm --config` as a proxy and "
        "point every agent at it via `LiteLLMProxyChatLLM` (or `provider='litellm'` with "
        "`api_base` set).\n"
    ),
]


def main() -> None:
    notebook = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    # Give every cell a stable id so nbformat doesn't warn.
    for i, cell in enumerate(notebook["cells"]):
        cell.setdefault("id", f"cell-{i:02d}")
    OUT.write_text(json.dumps(notebook, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
