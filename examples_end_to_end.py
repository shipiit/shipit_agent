"""Everything at once: skills, MCP, deferred tools, live output, subagent, usage."""
import sys, textwrap; sys.path.insert(0, '.')
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.agent_mixin import UpgradeMixin
from shipit_agent.models import ToolCall
from shipit_agent.skills.markdown import discover_skills
from shipit_agent.tools import core_tools
from shipit_agent.tests.test_graph import Reply, ScriptedLLM
from shipit_agent.tests.test_bridge import LegacyAgent
from shipit_agent.tests.test_mcp_and_skills import FakeMCPServer, FakeMCPTool, FakeConnection

@dataclass
class Agent(UpgradeMixin, LegacyAgent):
    pass

# 1 jira server with 30 tools -> deferred behind tool_search
jira = FakeMCPServer(
    "jira",
    [FakeMCPTool(f"op{i}", f"jira operation {i}") for i in range(29)]
    + [FakeMCPTool("create_issue", "Create a bug report in the tracker")],
    instructions="Always call list_projects before create_issue.",
)

skills = discover_skills("skills")

llm = ScriptedLLM(
    Reply(content="Let me plan this.", tool_calls=[
        ToolCall(name="todo", arguments={"items": [
            {"task": "load the review skill", "status": "in_progress"},
            {"task": "find the issue tool", "status": "pending"},
        ]})]),
    Reply(tool_calls=[ToolCall(name="load_skill", arguments={"skill_id": "code-review"})]),
    Reply(tool_calls=[ToolCall(name="tool_search", arguments={"query": "file a bug"})]),
    Reply(tool_calls=[ToolCall(name="create_issue__mcp__jira", arguments={"title": "leak"})]),
    Reply(tool_calls=[ToolCall(name="bash", arguments={"command": "echo scanning; echo done"})]),
    Reply(content="Filed the issue and verified the fix.",
          usage={"input_tokens": 1200, "output_tokens": 80}),
)

agent = Agent(
    llm=llm, model="google.gemma-4-31b",
    tools=core_tools("."), mcps=[jira], skill_registry=skills,
    model_parameters={"temperature": 0.3, "topK": 40, "maxContextTokens": 200000},
)
jira_conn = FakeConnection("jira")
agent.mcp_connect = lambda name: jira_conn

print("=" * 74)
print("PREFLIGHT (no model call)")
print("=" * 74)
pf = agent.preflight()
for k in ("model","schema_dialect","context_window","prefix_tokens","prefix_share",
          "tools_bound","tools_deferred","skills"):
    print(f"  {k:18} {pf[k]}")
print(f"  {'parameters':18} {pf['parameters']}")
print(f"  {'mcp':18} {pf['mcp']['servers']} server(s), {pf['mcp']['tools_deferred']} tools deferred, "
      f"instructions from {pf['mcp']['with_instructions']}")

print()
print("=" * 74)
print("LIVE EVENT STREAM")
print("=" * 74)
counts = {}
for e in agent.stream_v2("Review the auth module and file anything you find"):
    counts[e.type] = counts.get(e.type, 0) + 1
    p = e.payload
    if e.type == "text_delta":            print(f"  text        │ {p['chunk']!r}")
    elif e.type == "tool_called":         print(f"  tool        │ {p['tool']}  id={p['tool_call_id'][:14]}")
    elif e.type == "tool_output_delta":   print(f"  ├─ output   │ {p['chunk'][:52]!r}")
    elif e.type == "skill_loaded":        print(f"  skill       │ {p['skill_id']}  unlocked={p['unlocked_tools']}")
    elif e.type == "tools_discovered":    print(f"  discovered  │ {p['tools']}")
    elif e.type == "tools_rebound":       print(f"  rebound     │ now {p['bound']} tools bound")
    elif e.type == "mcp_attached":        print(f"  mcp         │ {p['server']}: {p['eager']} eager, {p['deferred']} deferred")
    elif e.type == "final_answer":        print(f"  ANSWER      │ {p['text']}")
    elif e.type == "run_summary":
        print(f"  summary     │ {p['usage']['total_tokens']} tokens, prefix_stable={p['prefix_stable']}")

r = agent.last_result_v2 if hasattr(agent,'last_result_v2') else agent._last_result_v2
print()
print("=" * 74)
print("RESULT")
print("=" * 74)
print(f"  output           {r.output}")
print(f"  primed skills    {r.metadata['primed_skills']}")
print(f"  discovered tools {r.metadata['discovered_tools']}")
print(f"  pairing ok       {r.metadata['pairing_ok']}")
print(f"  mcp call made    {jira_conn.calls}")
print(f"  event types      {sorted(counts)}")
