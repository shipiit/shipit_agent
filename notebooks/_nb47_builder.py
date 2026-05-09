"""Build notebooks/47_pm_pr_digest.ipynb.

PM persona: pull merged PRs across 3 repos, produce a digest, render a
dashboard, post the summary to Slack. GitHub + Slack calls are stubbed
with canned JSON so the notebook runs clean without credentials.

Run ``python notebooks/_nb47_builder.py`` to regenerate the notebook.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "47_pm_pr_digest.ipynb"


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
        "# 47 · PM — Weekly PR Digest Across 3 Repos\n"
        "\n"
        "**Persona:** Product Manager. **Tools exercised:** `GitHubTool`, "
        "`DashboardRenderTool`, `SlackTool`.\n"
        "\n"
        "End-to-end workflow:\n"
        "\n"
        "1. Pull all merged PRs this week from three product repos.\n"
        "2. Roll them into a per-repo digest.\n"
        "3. Render a weekly dashboard as a self-contained HTML artifact.\n"
        "4. Post a Slack summary to the product-updates channel.\n"
        "\n"
        "GitHub and Slack calls are stubbed with canned JSON so this runs "
        "clean without real API credentials. Swap the stubs for a real "
        "CredentialRecord to hit the live APIs.\n"
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
        "WORKSPACE = _find_notebooks_dir() / '_pm_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    md(
        "## 1 · Pick a model\n"
        "\n"
        "Defaults to `SimpleEchoLLM` so this notebook runs clean without creds. "
        "Uncomment one of the Bedrock / LiteLLM / LiteLLM-proxy blocks to wire "
        "in a real model.\n"
    ),
    code(
        "# from shipit_agent.llms import build_llm_from_settings\n"
        "\n"
        "# --- Option A: AWS Bedrock ------------------------------------\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'bedrock',\n"
        "#     'model': 'bedrock/anthropic.claude-sonnet-4-5-v2:0',\n"
        "# }, provider='bedrock')\n"
        "\n"
        "# --- Option B: LiteLLM direct ---------------------------------\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'litellm',\n"
        "#     'model': 'openai/gpt-4o-mini',\n"
        "# }, provider='litellm')\n"
        "\n"
        "# --- Option C: LiteLLM proxy ----------------------------------\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(\n"
        "#     model='gpt-4o-mini',\n"
        "#     api_base='https://litellm.my-company.internal',\n"
        "#     api_key='sk-proxy-token',\n"
        "# )\n"
        "\n"
        "# Zero-credential default — deterministic echo model.\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    md(
        "## 2 · Wire up credential records + stubbed HTTP\n"
        "\n"
        "Both `GitHubTool` and `SlackTool` are `HTTPConnectorToolBase` subclasses — "
        "they go through `_request_json(record=..., method=..., path=..., query=..., body=...)`. "
        "We replace that method with a canned-response function so the workflow "
        "runs end-to-end with zero external API traffic.\n"
    ),
    code(
        "from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore\n"
        "from shipit_agent.tools.github import GitHubTool\n"
        "from shipit_agent.tools.slack import SlackTool\n"
        "\n"
        "store = InMemoryCredentialStore()\n"
        "store.set(CredentialRecord(\n"
        "    key='github', provider='github',\n"
        "    secrets={'token': 'ghp_demo'},\n"
        "    metadata={'base_url': 'https://api.github.com', 'auth_scheme': 'Bearer'},\n"
        "))\n"
        "store.set(CredentialRecord(\n"
        "    key='slack', provider='slack',\n"
        "    secrets={'token': 'xoxb-demo'},\n"
        "))\n"
        "\n"
        "gh = GitHubTool(credential_store=store)\n"
        "slack = SlackTool(credential_store=store)\n"
        "print('tools ready:', gh.name, slack.name)\n"
    ),
    code(
        "# Canned GitHub responses for /repos/<owner>/<repo>/pulls with state=closed.\n"
        "_CANNED_PRS = {\n"
        "    'acme/api': [\n"
        "        {'number': 412, 'title': 'Fix rate-limit edge case on /search',\n"
        "         'state': 'closed', 'merged_at': '2026-04-22T10:15:00Z',\n"
        "         'user': {'login': 'adeleke'},\n"
        "         'html_url': 'https://github.com/acme/api/pull/412'},\n"
        "        {'number': 414, 'title': 'Add pagination cursor to /v2/orders',\n"
        "         'state': 'closed', 'merged_at': '2026-04-23T09:02:00Z',\n"
        "         'user': {'login': 'hmarta'},\n"
        "         'html_url': 'https://github.com/acme/api/pull/414'},\n"
        "    ],\n"
        "    'acme/web': [\n"
        "        {'number': 289, 'title': 'Dashboard sidebar redesign',\n"
        "         'state': 'closed', 'merged_at': '2026-04-21T14:40:00Z',\n"
        "         'user': {'login': 'rahul'},\n"
        "         'html_url': 'https://github.com/acme/web/pull/289'},\n"
        "        {'number': 291, 'title': 'Billing page empty-state copy tweak',\n"
        "         'state': 'closed', 'merged_at': '2026-04-22T16:05:00Z',\n"
        "         'user': {'login': 'kpatel'},\n"
        "         'html_url': 'https://github.com/acme/web/pull/291'},\n"
        "    ],\n"
        "    'acme/mobile': [\n"
        "        {'number': 178, 'title': 'Android push notifications crash fix',\n"
        "         'state': 'closed', 'merged_at': '2026-04-23T11:30:00Z',\n"
        "         'user': {'login': 'shinji'},\n"
        "         'html_url': 'https://github.com/acme/mobile/pull/178'},\n"
        "    ],\n"
        "}\n"
        "\n"
        "def _fake_github(*, record, method, path, query=None, body=None):\n"
        "    # Demo only — return canned PR lists.\n"
        "    for slug, prs in _CANNED_PRS.items():\n"
        "        if path == f'/repos/{slug}/pulls':\n"
        "            return prs\n"
        "    return []\n"
        "\n"
        "gh._request_json = _fake_github\n"
        "\n"
        "def _fake_slack(*, record, method, path, query=None, body=None):\n"
        "    # Demo only — return Slack-like {ok: True} payloads.\n"
        "    if path == '/chat.postMessage':\n"
        "        return {'ok': True, 'channel': body.get('channel'),\n"
        "                'ts': '1714000000.000100', 'message': {'text': body.get('text', '')}}\n"
        "    return {'ok': True}\n"
        "\n"
        "slack._request_json = _fake_slack\n"
        "print('stubs installed')\n"
    ),
    md(
        "## 3 · Pull merged PRs across 3 repos\n"
        "\n"
        "Each tool call goes through the same `ToolContext` path the Agent uses — "
        "so the round-trip mirrors what happens when an LLM emits a tool call.\n"
    ),
    code(
        "from shipit_agent.tools.base import ToolContext\n"
        "\n"
        "ctx = ToolContext(prompt='pm digest', state={'credential_store': store})\n"
        "REPOS = [('acme', 'api'), ('acme', 'web'), ('acme', 'mobile')]\n"
        "\n"
        "digest: dict[str, list[dict]] = {}\n"
        "for owner, repo in REPOS:\n"
        "    out = gh.run(ctx, action='list_pulls', owner=owner, repo=repo, state='closed')\n"
        "    items = out.metadata.get('items') or []\n"
        "    digest[f'{owner}/{repo}'] = items\n"
        "    print(f'{owner}/{repo}: {len(items)} merged PRs')\n"
    ),
    md(
        "## 4 · Render the weekly dashboard\n"
        "\n"
        "The `DashboardRenderTool` emits a self-contained HTML document we can "
        "ship as a PR-review-ready artifact or attach to the Slack post.\n"
    ),
    code(
        "from shipit_agent.tools.dashboard_render import DashboardRenderTool\n"
        "\n"
        "dash = DashboardRenderTool(workspace_root=WORKSPACE)\n"
        "\n"
        "metric_items = [\n"
        "    {'label': slug, 'value': str(len(prs)), 'sub': 'merged'}\n"
        "    for slug, prs in digest.items()\n"
        "]\n"
        "total = sum(len(v) for v in digest.values())\n"
        "metric_items.append({'label': 'Total', 'value': str(total), 'sub': 'this week'})\n"
        "\n"
        "timeline = []\n"
        "for slug, prs in digest.items():\n"
        "    for pr in prs:\n"
        "        timeline.append({\n"
        "            'period': pr['merged_at'][:10],\n"
        "            'head': f\"{slug} #{pr['number']}\",\n"
        "            'desc': pr['title'],\n"
        "            'dot_color': '#185fa5',\n"
        "            'tags': [{'text': pr.get('user', {}).get('login', '?'), 'color': 'blue'}],\n"
        "        })\n"
        "timeline.sort(key=lambda t: t['period'])\n"
        "\n"
        "result = dash.run(\n"
        "    ToolContext(prompt='pm digest', state={'artifact_workspace_root': str(WORKSPACE)}),\n"
        "    title='Weekly PR Digest — Acme Platform',\n"
        "    subtitle='Week of 2026-04-20',\n"
        "    lang='en',\n"
        "    sections=[\n"
        "        {'type': 'metrics', 'title': 'Merges by repo',\n"
        "         'columns': len(metric_items), 'items': metric_items},\n"
        "        {'type': 'timeline', 'title': 'Merge timeline', 'items': timeline},\n"
        "        {'type': 'verdict', 'title': 'PM takeaway',\n"
        "         'text': (f'**{total} PRs merged this week** across '\n"
        "                  f'{len(REPOS)} repos. Biggest driver: API '\n"
        "                  f'pagination + rate-limiting work.')},\n"
        "    ],\n"
        "    export=True,\n"
        ")\n"
        "print(result.text)\n"
        "print('artifact path:', result.metadata.get('path'))\n"
    ),
    md(
        "## 5 · Post a digest to Slack\n"
        "\n"
        "We post a plain-text summary of the digest to `#product-updates`. In a "
        "real run you'd also upload the HTML dashboard as a file attachment — "
        "here we just send a text message.\n"
    ),
    code(
        "text_lines = ['*Weekly PR Digest — week of 2026-04-20*', '']\n"
        "for slug, prs in digest.items():\n"
        "    text_lines.append(f'*{slug}* — {len(prs)} merged')\n"
        "    for pr in prs:\n"
        "        author = pr.get('user', {}).get('login', '?')\n"
        "        text_lines.append(f'  • #{pr[\"number\"]} {pr[\"title\"]} (@{author})')\n"
        "    text_lines.append('')\n"
        "text = '\\n'.join(text_lines)\n"
        "\n"
        "slack_out = slack.run(ctx, action='post_message',\n"
        "                       channel='C_PRODUCT_UPDATES', text=text)\n"
        "print(slack_out.text)\n"
    ),
    md(
        "## 6 · Autopilot would capture this HTML as an artifact\n"
        "\n"
        "Drop the same tools into `Autopilot(..., artifacts=True)` and the "
        "rendered dashboard flows through `ArtifactCollector.ingest_tool_metadata` "
        "automatically — no glue code.\n"
    ),
    code(
        "from shipit_agent.autopilot import ArtifactCollector\n"
        "\n"
        "collector = ArtifactCollector()\n"
        "collector.ingest_tool_metadata(result.metadata, iteration=1)\n"
        "for a in collector.all():\n"
        "    print(f'{a.kind:<6} {a.name:<30} {len(a.content):>6,} chars')\n"
    ),
    md(
        "## Next steps\n"
        "\n"
        "* Swap the stubs for a real `GitHubTool` credential (personal access "
        "token) to run this on your actual repos.\n"
        "* See `docs-app/content/source/tools/github.md` for the full action "
        "surface.\n"
        "* Wrap the workflow in an `Autopilot(...)` run so the digest happens on "
        "a daily schedule via the scheduler daemon (notebook 39).\n"
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
    for i, cell in enumerate(notebook["cells"]):
        cell.setdefault("id", f"cell-{i:02d}")
    OUT.write_text(json.dumps(notebook, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
