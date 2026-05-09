"""Build notebooks/48_designer_figma_review.ipynb.

Designer persona: read a Figma file + its comments, analyse rendered
frames via the VisionTool, produce a design-review dashboard. Figma
calls are stubbed; vision falls back to SimpleEchoLLM when no
vision-capable LLM is plugged in.

Run ``python notebooks/_nb48_builder.py`` to regenerate the notebook.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "48_designer_figma_review.ipynb"


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
        "# 48 · Designer — Figma Review Workflow\n"
        "\n"
        "**Persona:** Designer. **Tools exercised:** `FigmaTool`, `VisionTool`, "
        "`DashboardRenderTool`.\n"
        "\n"
        "End-to-end workflow:\n"
        "\n"
        "1. Read a Figma file (name, pages, last-modified).\n"
        "2. Pull unresolved comments on the file.\n"
        "3. Render selected frame nodes as PNGs.\n"
        "4. Ask the VisionTool to describe each frame (graceful fallback when no "
        "vision-capable LLM is wired up).\n"
        "5. Ship the whole thing as a design-review dashboard HTML.\n"
        "\n"
        "Figma HTTP calls are stubbed with canned JSON. The VisionTool uses "
        "whatever LLM you pass it — with `SimpleEchoLLM` the echo gives you the "
        "shape of the response; plug in a real Claude/GPT-4o LLM to get actual "
        "vision analysis.\n"
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
        "WORKSPACE = _find_notebooks_dir() / '_designer_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    md(
        "## 1 · Pick a model\n"
        "\n"
        "Defaults to `SimpleEchoLLM`. Swap in a vision-capable LLM (Claude, "
        "GPT-4o, Bedrock Claude) to get real image analysis in section 4.\n"
    ),
    code(
        "# from shipit_agent.llms import build_llm_from_settings\n"
        "\n"
        "# Bedrock Claude (vision-capable):\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'bedrock',\n"
        "#     'model': 'bedrock/anthropic.claude-sonnet-4-5-v2:0',\n"
        "# }, provider='bedrock')\n"
        "\n"
        "# LiteLLM direct (GPT-4o is vision-capable):\n"
        "# llm = build_llm_from_settings({\n"
        "#     'provider': 'litellm', 'model': 'openai/gpt-4o',\n"
        "# }, provider='litellm')\n"
        "\n"
        "# LiteLLM proxy:\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(model='gpt-4o', api_base='https://litellm.internal', api_key='sk-...')\n"
        "\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    md(
        "## 2 · Stub the Figma HTTP layer\n"
        "\n"
        "`FigmaTool` is an `HTTPConnectorToolBase` — we replace `_request_json` "
        "with canned responses that look like real Figma API payloads.\n"
    ),
    code(
        "from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore\n"
        "from shipit_agent.tools.figma import FigmaTool\n"
        "\n"
        "store = InMemoryCredentialStore()\n"
        "store.set(CredentialRecord(\n"
        "    key='figma', provider='figma',\n"
        "    secrets={'token': 'figma-demo-token'},\n"
        "    metadata={'base_url': 'https://api.figma.com'},\n"
        "))\n"
        "figma = FigmaTool(credential_store=store)\n"
        "\n"
        "FILE_KEY = 'ABCDEF123456'\n"
        "\n"
        "def _fake_figma(*, record, method, path, query=None, body=None):\n"
        "    if path == f'/v1/files/{FILE_KEY}':\n"
        "        return {\n"
        "            'name': 'Billing v3 — Empty States',\n"
        "            'lastModified': '2026-04-23T09:12:00Z',\n"
        "            'document': {'children': [\n"
        "                {'id': '1:2', 'name': 'Cover',   'type': 'CANVAS'},\n"
        "                {'id': '1:5', 'name': 'Screens', 'type': 'CANVAS'},\n"
        "                {'id': '1:8', 'name': 'States',  'type': 'CANVAS'},\n"
        "            ]},\n"
        "        }\n"
        "    if path == f'/v1/files/{FILE_KEY}/comments':\n"
        "        return {'comments': [\n"
        "            {'id': 'c1', 'user': {'handle': 'mira'},\n"
        "             'message': 'Error state contrast feels too low — bump to 4.5:1.',\n"
        "             'resolved_at': None},\n"
        "            {'id': 'c2', 'user': {'handle': 'rahul'},\n"
        "             'message': 'Primary CTA should sit above the fold on mobile.',\n"
        "             'resolved_at': None},\n"
        "            {'id': 'c3', 'user': {'handle': 'shinji'},\n"
        "             'message': 'Copy for zero-invoices state is too apologetic.',\n"
        "             'resolved_at': None},\n"
        "        ]}\n"
        "    if path == f'/v1/images/{FILE_KEY}':\n"
        "        return {'images': {\n"
        "            '1:20': 'https://example.com/figma-fake/frame-empty-invoices.png',\n"
        "            '1:21': 'https://example.com/figma-fake/frame-error-card-declined.png',\n"
        "        }}\n"
        "    return {}\n"
        "\n"
        "figma._request_json = _fake_figma\n"
        "print('figma stubs installed')\n"
    ),
    md("## 3 · Read the file + pull open comments"),
    code(
        "from shipit_agent.tools.base import ToolContext\n"
        "\n"
        "ctx = ToolContext(prompt='design review', state={'credential_store': store})\n"
        "\n"
        "file_out = figma.run(ctx, action='get_file', file_key=FILE_KEY)\n"
        "print(file_out.text)\n"
        "\n"
        "comments_out = figma.run(ctx, action='get_comments', file_key=FILE_KEY)\n"
        "print()\n"
        "print(comments_out.text)\n"
        "\n"
        "img_out = figma.run(ctx, action='get_image', file_key=FILE_KEY,\n"
        "                     ids=['1:20', '1:21'], format='png', scale=2)\n"
        "print()\n"
        "print(img_out.text)\n"
        "images = img_out.metadata.get('images', {})\n"
    ),
    md(
        "## 4 · Vision pass on rendered frames\n"
        "\n"
        "`VisionTool` takes any URL, file path, data URL, or raw base64 and "
        "forwards it to a vision-capable LLM. With `SimpleEchoLLM` you get the "
        "shape of the request; plug in a real Claude/GPT-4o to get actual "
        "analysis of each frame.\n"
    ),
    code(
        "from shipit_agent.tools.vision import VisionTool\n"
        "\n"
        "vision = VisionTool(llm=llm)\n"
        "vision_notes: list[dict] = []\n"
        "for node_id, url in images.items():\n"
        "    v = vision.run(ctx, image=url,\n"
        "                    prompt=('You are a design reviewer. What are the '\n"
        "                            'top 3 visual issues on this frame? Focus '\n"
        "                            'on contrast, hierarchy, and empty-state copy.'))\n"
        "    vision_notes.append({'node_id': node_id, 'url': url, 'notes': v.text})\n"
        "    print(f'{node_id}: {v.text[:160]}')\n"
    ),
    md(
        "## 5 · Design-review dashboard\n"
        "\n"
        "Bundle the file header, comments, vision notes, and a verdict into a "
        "single HTML document the designer can share in a PR.\n"
    ),
    code(
        "from shipit_agent.tools.dashboard_render import DashboardRenderTool\n"
        "\n"
        "dash = DashboardRenderTool(workspace_root=WORKSPACE)\n"
        "\n"
        "comment_items = comments_out.metadata.get('items') or []\n"
        "\n"
        "timeline = [\n"
        "    {'period': c.get('id', '?'),\n"
        "     'head': c.get('user', {}).get('handle', '?'),\n"
        "     'desc': c.get('message', ''),\n"
        "     'dot_color': '#ba7517',\n"
        "     'tags': [{'text': 'open', 'color': 'amber'}]}\n"
        "    for c in comment_items\n"
        "]\n"
        "\n"
        "cards = [\n"
        "    {'title': f'Frame {n[\"node_id\"]}', 'rows': [\n"
        "        {'strong': 'URL:', 'text': n['url'], 'dot_color': '#185fa5'},\n"
        "        {'strong': 'Notes:', 'text': (n['notes'] or '(echo — plug in a vision LLM)')[:240],\n"
        "         'dot_color': '#1d9e75'},\n"
        "    ]}\n"
        "    for n in vision_notes\n"
        "]\n"
        "\n"
        "result = dash.run(\n"
        "    ToolContext(prompt='design review', state={'artifact_workspace_root': str(WORKSPACE)}),\n"
        "    title=f'Design Review — {file_out.metadata[\"file\"][\"name\"]}',\n"
        "    subtitle='Generated from Figma comments + vision analysis',\n"
        "    lang='en',\n"
        "    sections=[\n"
        "        {'type': 'metrics', 'title': 'Review snapshot', 'columns': 3, 'items': [\n"
        "            {'label': 'Pages', 'value': str(len(file_out.metadata['file']['document']['children']))},\n"
        "            {'label': 'Open comments', 'value': str(len(comment_items))},\n"
        "            {'label': 'Frames analysed', 'value': str(len(vision_notes))},\n"
        "        ]},\n"
        "        {'type': 'timeline', 'title': 'Open comments', 'items': timeline},\n"
        "        {'type': 'cards',    'title': 'Vision analysis', 'columns': 2, 'cards': cards},\n"
        "        {'type': 'verdict',  'title': 'Reviewer verdict',\n"
        "         'text': ('Three blockers: **contrast on error state**, **CTA above fold on mobile**, '\n"
        "                  '**softer empty-state copy**. Ship fixes before QA hand-off.')},\n"
        "    ],\n"
        "    export=True,\n"
        ")\n"
        "print(result.text)\n"
        "print('artifact path:', result.metadata.get('path'))\n"
    ),
    md(
        "## Next steps\n"
        "\n"
        "* Swap `SimpleEchoLLM` for a real vision-capable LLM (Claude Sonnet, "
        "GPT-4o) in section 1 — you'll get genuine design critique instead of "
        "echoed prompts.\n"
        "* See `docs-app/content/source/tools/figma.md` for the full Figma "
        "action surface (projects, components, rendering, posting replies).\n"
        "* Attach the exported HTML to a Figma comment with "
        "`figma.run(..., action='post_comment')` to close the loop.\n"
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
