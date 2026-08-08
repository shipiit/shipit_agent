"""Build the high-depth optimized project-agent validation notebook."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "77_super_agent_live_validation.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
    }


def code(text: str, *tags: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {"tags": list(tags)},
        "execution_count": None,
        "outputs": [],
        "source": text.splitlines(keepends=True),
    }


CELLS = [
    md(
        "# Super Agent - high-depth live validation\n\n"
        "This notebook validates the main `Agent` as a long-running coding "
        "agent: optimized project setup, complete capability discovery, skills, "
        "MCP provenance, permission gates, durable sessions, cache accounting, "
        "multimodal attachments, and live tool-output chunks.\n\n"
        "The **CI acceptance cell** is deterministic and free. The later cells "
        "reuse the real Gemma-on-Bedrock configuration from notebooks 74/75; "
        "set `RUN_LIVE=True` only when AWS credentials are available."
    ),
    md(
        "## Validation matrix\n\n"
        "| Layer | Assertion |\n|---|---|\n"
        "| Project agent | optimized code mode, context limit, bounded model output |\n"
        "| Tools | real write/read plus true incremental custom output |\n"
        "| Streaming | started/delta/completed ordering and complete canonical result |\n"
        "| Permissions | unlisted actions denied; selected project actions allowed |\n"
        "| MCP | local server result and server provenance visible in chunk metadata |\n"
        "| Sessions | same session ID resumes from `.shipit/sessions/` |\n"
        "| Cache | cache read/create token totals survive into run events |\n"
        "| Media | screenshot reference becomes a provider-neutral image block |\n"
        "| Live model | deep repo audit plus a safe isolated edit-and-verify flow |"
    ),
    md("## 1. Locate this checkout"),
    code(
        "import sys\n"
        "from pathlib import Path\n\n"
        "def repo_root(start: Path) -> Path:\n"
        "    for candidate in [start.resolve(), *start.resolve().parents]:\n"
        "        if (candidate / 'shipit_agent' / '__init__.py').exists():\n"
        "            return candidate\n"
        "    raise RuntimeError(f'Cannot find shipit_agent from {start}')\n\n"
        "REPO = repo_root(Path.cwd())\n"
        "if str(REPO) not in sys.path:\n"
        "    sys.path.insert(0, str(REPO))\n"
        "print('repo:', REPO)\n",
        "ci",
    ),
    md(
        "## 2. Deterministic acceptance suite\n\n"
        "This executes the real runtime, project tools, permission engine, MCP "
        "registry, session stores, media parser, doctor, and stream pipeline. "
        "Only the model is scripted so CI is repeatable."
    ),
    code(
        "import tempfile\n"
        "from typing import Any\n\n"
        "from shipit_agent import (\n"
        "    Agent, FunctionTool, Guardrails, PermissionEngine, RouterPolicy,\n"
        "    ToolOutputChunk,\n"
        ")\n"
        "from shipit_agent.llms import LLMResponse, SimpleEchoLLM\n"
        "from shipit_agent.mcp import MCPServer, MCPTool\n"
        "from shipit_agent.models import ToolCall\n"
        "from shipit_agent.multimodal import MediaParser, build_multimodal_message\n"
        "from shipit_agent.permissions import PermissionDecision\n\n"
        "class ScenarioLLM:\n"
        "    model = 'test-model-128k'\n"
        "    def __init__(self, calls):\n"
        "        self.calls = list(calls)\n"
        "        self.index = 0\n"
        "    def complete(self, **kwargs: Any):\n"
        "        if self.index < len(self.calls):\n"
        "            call = self.calls[self.index]\n"
        "            self.index += 1\n"
        "            return LLMResponse(\n"
        "                content='', tool_calls=[ToolCall(name=call[0], arguments=call[1])],\n"
        "                usage={'prompt_tokens': 40, 'completion_tokens': 8,\n"
        "                       'cache_read_input_tokens': 30,\n"
        "                       'cache_creation_input_tokens': 4},\n"
        "            )\n"
        "        return LLMResponse(\n"
        "            content='acceptance complete',\n"
        "            usage={'prompt_tokens': 20, 'completion_tokens': 5,\n"
        "                   'cache_read_input_tokens': 15},\n"
        "        )\n\n"
        "def stream_probe():\n"
        "    yield ToolOutputChunk('phase-1\\n', {'phase': 1})\n"
        "    yield ToolOutputChunk('phase-2\\n', {'phase': 2})\n"
        "    yield 'phase-3\\n'\n\n"
        "workspace = Path(tempfile.mkdtemp(prefix='shipit-super-agent-'))\n"
        "policy = PermissionEngine(\n"
        "    allow=['stream_probe', 'write_file', 'read_file'],\n"
        "    default_decision=PermissionDecision.DENY,\n"
        ")\n"
        "model = ScenarioLLM([\n"
        "    ('stream_probe', {}),\n"
        "    ('write_file', {'path': 'report.txt', 'content': 'verified\\n'}),\n"
        "    ('read_file', {'path': 'report.txt'}),\n"
        "])\n"
        "agent = Agent.for_project(\n"
        "    llm=model, project_root=workspace, optimized=True,\n"
        "    tools=[FunctionTool.from_callable(stream_probe)],\n"
        "    permissions=policy, guardrails=Guardrails(),\n"
        "    router_policy=RouterPolicy(auto_plan=False), auto_use_skills=False,\n"
        ")\n"
        "events = list(agent.stream('Run the full deterministic acceptance flow.'))\n"
        "deltas = [e for e in events if e.type == 'tool_output_delta']\n"
        "assert (workspace / 'report.txt').read_text() == 'verified\\n'\n"
        "assert ''.join(e.payload['chunk'] for e in deltas[:1]) == 'phase-1\\nphase-2\\nphase-3\\n'\n"
        "assert all(e.payload['buffered'] for e in events if e.type == 'tool_output_started')\n"
        "assert agent.code_mode and agent.max_iterations == 8\n"
        "assert agent.max_tool_output_chars == 16_000\n"
        "completed = next(e for e in reversed(events) if e.type == 'run_completed')\n"
        "assert completed.payload['usage']['cache_read_input_tokens'] == 105\n\n"
        "# Permission denial is checked without relying on model behavior.\n"
        "assert policy.check('bash', {'command': 'rm -rf /'}).denied\n\n"
        "# Local MCP tools retain server provenance and use the same stream.\n"
        "mcp = MCPServer(name='knowledge').register(MCPTool(\n"
        "    name='lookup', description='Lookup facts',\n"
        "    handler=lambda **kwargs: 'mcp-fact',\n"
        "))\n"
        "mcp_agent = Agent(\n"
        "    llm=ScenarioLLM([('lookup', {})]), mcps=[mcp],\n"
        "    auto_use_skills=False, router_policy=RouterPolicy(auto_plan=False),\n"
        ")\n"
        "mcp_events = list(mcp_agent.stream('lookup'))\n"
        "mcp_delta = next(e for e in mcp_events if e.type == 'tool_output_delta')\n"
        "assert mcp_delta.payload['chunk'] == 'mcp-fact'\n"
        "assert mcp_delta.payload['chunk_metadata']['server'] == 'knowledge'\n\n"
        "# Durable sessions survive agent reconstruction.\n"
        "first = Agent.for_project(llm=SimpleEchoLLM(), project_root=workspace, optimized=True)\n"
        "first.chat_session(session_id='main').send('remember this checkpoint')\n"
        "second = Agent.for_project(llm=SimpleEchoLLM(), project_root=workspace, optimized=True)\n"
        "assert second.chat_session(session_id='main').history()\n"
        "assert (workspace / '.shipit' / 'sessions' / 'main.json').exists()\n\n"
        "# Screenshot/media references preserve text-image-text ordering.\n"
        "parsed = MediaParser(allowlist_domains=['cdn.example.com']).parse(\n"
        "    'Inspect ![error screenshot](https://cdn.example.com/error.png) carefully.'\n"
        ")\n"
        "media_message = build_multimodal_message(parsed)\n"
        "assert [block['type'] for block in media_message['content']] == ['text', 'image', 'text']\n\n"
        "doctor = agent.doctor()\n"
        "assert not any(check.status == 'fail' for check in doctor.checks)\n"
        "print('PASS: optimized project agent')\n"
        "print('PASS: live tool chunks and canonical results')\n"
        "print('PASS: permissions, MCP, sessions, cache, media, doctor')\n"
        "print('workspace:', workspace)\n",
        "ci",
    ),
    md(
        "### Inspect every event\n\n"
        "This view intentionally prints every tool chunk. `call_id` separates "
        "parallel streams; `tool_completed` remains the complete canonical value."
    ),
    code(
        "for event in events:\n"
        "    if event.type == 'tool_output_delta':\n"
        "        p = event.payload\n"
        "        print(f\"[{p['call_id']} #{p['sequence']}] {p['chunk']}\", end='')\n"
        "    elif event.type in {'tool_called', 'tool_completed', 'tool_denied'}:\n"
        "        print(f\"\\n{event.type}: {event.payload.get('tool')}\")\n",
        "ci",
    ),
    md("## 3. Capability, skill, connection, and efficiency report"),
    code(
        "report = agent.doctor()\n"
        "for check in report.checks:\n"
        '    print(f"{check.status.upper():4} {check.name:14} {check.message}")\n'
        "    if check.name in {'tools', 'skills', 'mcps', 'connections', 'efficiency'}:\n"
        "        print('    ', check.details)\n",
        "ci",
    ),
    md(
        "## 4. Configure the real model from notebooks 74/75\n\n"
        "This uses the existing Bedrock Mantle provider. It is opt-in because "
        "it costs money and requires the local provider checkout plus AWS credentials."
    ),
    code(
        "import os\n"
        "RUN_LIVE = os.getenv('SHIPIT_RUN_LIVE', '').lower() in {'1', 'true', 'yes'}\n"
        "PROVIDER = Path(\n"
        "    '/Users/rahulraj/Documents/MYWORK/AFTDRK/CACHE/DRK_CACHE_BACK'\n"
        "    '/drk_cache/llm/bedrock_mantle_provider.py'\n"
        ")\n"
        "MODEL = 'bedrock-mantle/google.gemma-4-26b-a4b'\n\n"
        "def configured_llm():\n"
        "    import importlib.util\n"
        "    spec = importlib.util.spec_from_file_location('bedrock_mantle_provider', PROVIDER)\n"
        "    module = importlib.util.module_from_spec(spec)\n"
        "    sys.modules['bedrock_mantle_provider'] = module\n"
        "    spec.loader.exec_module(module)\n"
        "    module.ensure_registered()\n"
        "    from shipit_agent.llms import LiteLLMChatLLM\n"
        "    return LiteLLMChatLLM(model=MODEL)\n\n"
        "print('live enabled:', RUN_LIVE)\n"
        "print('provider exists:', PROVIDER.exists())\n",
        "live",
    ),
    md(
        "## 5. Deep live read-only architecture audit\n\n"
        "The prompt forces an evidence-based investigation across the main agent, "
        "runtime, MCP, skills, permissions, sessions, caching, and streaming. "
        "The agent may inspect this repository but cannot modify it."
    ),
    code(
        "if RUN_LIVE:\n"
        "    from shipit_agent.builtins import get_builtin_tool_map\n"
        "    audit_map = get_builtin_tool_map(llm=None, project_root=str(REPO))\n"
        "    audit_tools = [audit_map[name] for name in ('read_file', 'grep_files')]\n"
        "    live_policy = PermissionEngine(\n"
        "        allow=['read_file', 'grep_files'],\n"
        "        default_decision=PermissionDecision.DENY,\n"
        "    )\n"
        "    live_agent = Agent(\n"
        "        llm=configured_llm(), project_root=REPO, tools=audit_tools,\n"
        "        permissions=live_policy, max_iterations=16,\n"
        "        context_window_tokens=128_000, max_tool_output_chars=16_000,\n"
        "        progress_summaries=True, auto_use_skills=False,\n"
        "    )\n"
        "    deep_prompt = '''\n"
        "Perform a rigorous architecture audit of this coding agent. Use tools; do not guess.\n"
        "Do not inspect build/, dist/, site/, or .venv/. First call read_file on these exact\n"
        "source paths: shipit_agent/agent.py, shipit_agent/runtime_core.py,\n"
        "shipit_agent/runtime.py, shipit_agent/async_runtime.py, shipit_agent/mcp.py,\n"
        "shipit_agent/permissions.py, shipit_agent/tool_runner.py,\n"
        "shipit_agent/tools/helpers.py, and shipit_agent/streaming.py. Use grep_files\n"
        "inside shipit_agent only for symbols you must verify. Cite exact source paths.\n"
        "Answer with: (1) evidence table with file paths, (2) exact tool/skill/MCP\n"
        "lifecycle, (3) token and prompt-cache controls, (4) long-session behavior,\n"
        "(5) permission and secret boundaries, (6) sync/async parity risks, and\n"
        "(7) five highest-value improvements. Separate verified facts from inference.\n"
        "'''\n"
        "    live_events = []\n"
        "    for event in live_agent.stream(deep_prompt):\n"
        "        live_events.append(event)\n"
        "        if event.type in {'text_delta', 'tool_output_delta'}:\n"
        "            print(event.payload.get('chunk', ''), end='', flush=True)\n"
        "        elif event.type == 'tool_called':\n"
        "            print(f\"\\n\\nCALL {event.payload['call_id']}: {event.payload['tool']}\")\n"
        "    read_calls = [e for e in live_events if e.type == 'tool_called' and\n"
        "                  e.payload.get('tool') == 'read_file']\n"
        "    assert len(read_calls) >= 5, f'not enough source reads: {len(read_calls)}'\n"
        "    assert any(e.type == 'tool_output_delta' for e in live_events)\n"
        "    assert not any(e.type == 'tool_denied' and e.payload.get('tool') in\n"
        "                   {'read_file', 'grep_files', 'glob_files'} for e in live_events)\n"
        "else:\n"
        "    print('Skipped paid live audit. Set RUN_LIVE=True to execute it.')\n",
        "live",
    ),
    md(
        "## 6. Live isolated edit-and-verify challenge\n\n"
        "This is the coding-agent test: operate only inside a temporary project, "
        "read requirements, write an implementation, inspect it, and run a verifier."
    ),
    code(
        "if RUN_LIVE:\n"
        "    import tempfile\n"
        "    challenge = Path(tempfile.mkdtemp(prefix='shipit-live-project-'))\n"
        "    (challenge / 'SPEC.md').write_text(\n"
        "        '# Task\\nCreate stats.py with summarize(values). Return count, min, max, mean. '\n"
        "        'Reject an empty list with ValueError. Add test_stats.py.\\n'\n"
        "    )\n"
        "    edit_policy = PermissionEngine(\n"
        "        allow=['read_file', 'write_file', 'edit_file', 'grep_files',\n"
        "               'glob_files', 'bash', 'tool_search', 'describe_binding',\n"
        "               'execute_code'],\n"
        "        default_decision=PermissionDecision.DENY,\n"
        "    )\n"
        "    coder = Agent.for_project(\n"
        "        llm=configured_llm(), project_root=challenge, optimized=True,\n"
        "        permissions=edit_policy, max_iterations=12,\n"
        "    )\n"
        "    edit_events = list(coder.stream(\n"
        "        'Read SPEC.md, implement it, add strong tests, run pytest, and fix failures.'\n"
        "    ))\n"
        "    assert (challenge / 'stats.py').exists()\n"
        "    assert (challenge / 'test_stats.py').exists()\n"
        "    edit_output = '\\n'.join(\n"
        "        str(e.payload.get('output', '')) for e in edit_events\n"
        "        if e.type == 'tool_completed'\n"
        "    )\n"
        "    assert 'passed' in edit_output.lower(), edit_output[-2000:]\n"
        "    assert not any(e.type == 'tool_failed' for e in edit_events)\n"
        "    denied = [e for e in edit_events if e.type == 'tool_denied']\n"
        "    assert all(e.payload.get('decision') == 'deny' for e in denied)\n"
        "    assert any(e.type == 'tool_output_delta' for e in edit_events)\n"
        "    print('challenge:', challenge)\n"
        "    print('tool calls:', sum(e.type == 'tool_called' for e in edit_events))\n"
        "    print('safely denied:', [e.payload.get('tool') for e in denied])\n"
        "else:\n"
        "    print('Skipped paid edit challenge. Set RUN_LIVE=True to execute it.')\n",
        "live",
    ),
    md(
        "## Pass criteria\n\n"
        "- The CI cell prints three PASS lines with no assertion failures.\n"
        "- Live runs emit `tool_output_delta` before `tool_completed`.\n"
        "- Every concurrent stream is attributable through `call_id`.\n"
        "- Read-only audit attempts cannot mutate the repository.\n"
        "- The edit challenge writes only in its temporary project and passes tests.\n"
        "- Durable history appears under `.shipit/sessions/`; model context remains bounded.\n"
        "- Media is represented as ordered content blocks rather than flattened text."
    ),
]


notebook = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

for index, cell in enumerate(notebook["cells"]):
    cell["id"] = f"shipit-super-agent-{index:02d}"

OUT.write_text(json.dumps(notebook, indent=1) + "\n")
print(f"wrote {OUT} ({len(CELLS)} cells)")
