"""`Agent(code_mode=True)` — the wiring that turns code mode on."""

from __future__ import annotations

import json


from shipit_agent import Agent, ApprovalQueue
from shipit_agent.codemode import CORE_TOOLS, binding_index, build_bindings
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.permissions import PermissionEngine
from shipit_agent.tools.base import ToolOutput


def resource(name, actions, result="ok", record=None):
    """A connector-shaped tool: one action enum over shared parameters."""

    class Resource:
        def __init__(self):
            self.name = name
            self.description = f"The {name} resource."
            self.prompt_instructions = ""

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": self.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": list(actions)},
                            "sql": {"type": "string"},
                            "title": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
            }

        def run(self, context, **kwargs):
            if record is not None:
                record.append((name, kwargs))
            return ToolOutput(text=result)

    return Resource()


class ScriptedLLM:
    """Replays (text, tool_calls) steps and records what it was shown."""

    model = "test-model"

    def __init__(self, script):
        self.script = list(script)
        self.n = 0
        self.seen_tools: list[list[str]] = []
        self.seen_schemas: list[list[dict]] = []
        self.seen_system: list[str] = []

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        self.seen_schemas.append(list(tools or []))
        self.seen_tools.append(
            [(t.get("function") or {}).get("name") for t in (tools or [])]
        )
        self.seen_system.append(system_prompt or "")
        step = self.script[self.n] if self.n < len(self.script) else ("done", [])
        self.n += 1
        return LLMResponse(
            content=step[0],
            tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
        )


def build_agent(script, tools, **kwargs):
    kwargs.setdefault("auto_use_skills", False)
    kwargs.setdefault("max_iterations", 4)
    return Agent(llm=ScriptedLLM(script), tools=tools, **kwargs)


WAREHOUSE = "northwind,820\nglobex,4100\nacme,650"


class TestToolCatalogue:
    def test_code_mode_shrinks_the_advertised_tool_list(self) -> None:
        tools = [
            resource("warehouse", ["query"]),
            resource("linear", ["create_issue"]),
            resource("stripe", ["create_charge"]),
        ]
        plain = build_agent([("done", [])], tools)
        plain.run("hi")
        coded = build_agent([("done", [])], tools, code_mode=True)
        coded.run("hi")

        assert set(plain.llm.seen_tools[0]) >= {"warehouse", "linear", "stripe"}
        # Resources are gone from the schema block; they live in `env` now.
        assert "warehouse" not in coded.llm.seen_tools[0]
        assert "execute_code" in coded.llm.seen_tools[0]

    def test_core_tools_survive(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        agent = Agent(
            llm=ScriptedLLM([("done", [])]),
            tools=get_builtin_tools(llm=None, project_root="."),
            code_mode=True,
            auto_use_skills=False,
        )
        agent.run("hi")
        advertised = set(agent.llm.seen_tools[0])
        assert {"read_file", "bash", "execute_code", "describe_binding"} <= advertised
        assert "stripe" not in advertised and "github" not in advertised

    def test_the_prompt_collapse_is_real_end_to_end(self) -> None:
        """The reason code mode exists, measured on what actually goes out.

        Both halves count: the tool schemas *and* the per-tool instruction
        block in the system prompt. Filtering only the schemas leaves the
        larger half untouched.
        """
        from shipit_agent.builtins import get_builtin_tools

        tools = get_builtin_tools(llm=None, project_root=".")

        def measure(**kwargs):
            agent = Agent(
                llm=ScriptedLLM([("d", [])]), tools=tools,
                auto_use_skills=False, **kwargs,
            )
            agent.run("hi")
            return (
                len(json.dumps(agent.llm.seen_schemas[0]))
                + len(agent.llm.seen_system[0])
            )

        plain = measure(tool_context_mode="full")
        coded = measure(code_mode=True)
        assert coded < plain * 0.6, f"code mode {coded} vs {plain}"

    def test_the_tools_prompt_shrinks_too_not_just_the_schemas(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        tools = get_builtin_tools(llm=None, project_root=".")
        plain = Agent(
            llm=ScriptedLLM([("d", [])]),
            tools=tools,
            auto_use_skills=False,
            tool_context_mode="full",
        )
        plain.run("hi")
        coded = Agent(llm=ScriptedLLM([("d", [])]), tools=tools, code_mode=True,
                      auto_use_skills=False)
        coded.run("hi")
        # A bound resource keeps its one-line index entry — that is the point —
        # but its full instruction block is gone.
        # build_tools_prompt emits "- <name>: <description>" plus a long
        # guidance block per tool; that whole entry is what must disappear.
        assert "- stripe [" in plain.llm.seen_system[0]
        assert "- stripe:" not in coded.llm.seen_system[0]
        assert "- env.STRIPE" in coded.llm.seen_system[0]
        assert len(coded.llm.seen_system[0]) < len(plain.llm.seen_system[0]) * 0.6

    def test_execute_code_is_added_automatically(self) -> None:
        # It is opt-in as a builtin; code mode is what opts in.
        agent = build_agent([("done", [])], [resource("warehouse", ["query"])],
                            code_mode=True)
        agent.run("hi")
        assert "execute_code" in agent.llm.seen_tools[0]

    def test_off_by_default(self) -> None:
        agent = build_agent([("done", [])], [resource("warehouse", ["query"])])
        agent.run("hi")
        assert "warehouse" in agent.llm.seen_tools[0]
        assert "execute_code" not in agent.llm.seen_tools[0]

    def test_large_plain_agent_uses_progressive_discovery_automatically(self) -> None:
        tools = [resource(f"service_{index}", ["query"]) for index in range(13)]
        agent = build_agent([("done", [])], tools)

        result = agent.run("hello")

        advertised = set(agent.llm.seen_tools[0])
        assert "service_0" not in advertised
        assert {"tool_search", "call_tool"} <= advertised
        assert "execute_code" not in advertised
        assert result.metadata["effective_code_mode"] is False
        assert result.metadata["progressive_tool_context"] is True
        assert result.metadata["hidden_tool_count"] == 13

    def test_full_mode_keeps_large_catalog_eager(self) -> None:
        tools = [resource(f"service_{index}", ["query"]) for index in range(13)]
        agent = build_agent(
            [("done", [])], tools, tool_context_mode="full"
        )

        result = agent.run("hello")

        assert "service_0" in agent.llm.seen_tools[0]
        assert result.metadata["progressive_tool_context"] is False

    def test_large_schemas_trigger_lazy_mode_even_with_few_tools(self) -> None:
        tools = [resource("warehouse", [f"operation_{i}" for i in range(300)])]
        agent = build_agent(
            [("done", [])], tools, tool_context_threshold_chars=1_000
        )

        result = agent.run("hello")

        assert result.metadata["progressive_tool_context"] is True
        assert "warehouse" not in agent.llm.seen_tools[0]

    def test_mcp_or_connector_can_be_called_through_stable_gateway(self) -> None:
        calls: list = []
        agent = build_agent(
            [
                (
                    "",
                    [("call_tool", {
                        "name": "warehouse",
                        "arguments": {"action": "query", "sql": "SELECT 1"},
                    })],
                ),
                ("Found the rows.", []),
            ],
            [resource("warehouse", ["query"], result=WAREHOUSE, record=calls)],
            code_mode=True,
        )

        result = agent.run("Query the warehouse")

        assert calls == [("warehouse", {"action": "query", "sql": "SELECT 1"})]
        assert result.output == "Found the rows."
        assert any(event.payload.get("tool") == "warehouse" for event in result.events)


class TestSystemPrompt:
    def test_bindings_are_listed(self) -> None:
        agent = build_agent(
            [("done", [])],
            [resource("warehouse", ["query"]), resource("linear", ["create_issue"])],
            code_mode=True,
        )
        agent.run("hi")
        prompt = agent.llm.seen_system[0]
        assert "env.WAREHOUSE" in prompt and "env.LINEAR" in prompt
        assert "describe_binding" in prompt

    def test_the_index_is_one_line_per_resource(self) -> None:
        bindings = build_bindings([resource("warehouse", ["query", "load"])])
        index = binding_index(bindings)
        assert index.count("- env.") == 1  # not one line per method

    def test_no_bindings_means_no_section(self) -> None:
        assert binding_index({}) == ""

    def test_a_core_only_agent_gets_no_index(self) -> None:
        from shipit_agent.builtins import get_builtin_tool_map

        core = [t for n, t in get_builtin_tool_map(llm=None, project_root=".").items()
                if n in CORE_TOOLS]
        agent = Agent(llm=ScriptedLLM([("d", [])]), tools=core, code_mode=True,
                      auto_use_skills=False)
        agent.run("hi")
        assert "env." not in agent.llm.seen_system[0]


class TestExecution:
    def test_env_calls_reach_the_real_tools(self) -> None:
        calls: list = []
        agent = build_agent(
            [
                ("", [("execute_code", {"code":
                    'rows = env.WAREHOUSE.query(sql="SELECT 1")\nprint(rows)'})]),
                ("Found them.", []),
            ],
            [resource("warehouse", ["query"], result=WAREHOUSE, record=calls)],
            code_mode=True,
        )
        result = agent.run("Which accounts are at risk?")
        assert calls == [("warehouse", {"action": "query", "sql": "SELECT 1"})]
        assert "northwind" in [m for m in result.messages if m.role == "tool"][0].content

    def test_one_call_composes_several_resources(self) -> None:
        """The reason code mode exists — five tool calls become one."""
        calls: list = []
        agent = build_agent(
            [
                ("", [("execute_code", {"code": """
rows = env.WAREHOUSE.query(sql="SELECT account, mrr FROM bookings")
at_risk = [l.split(",") for l in rows.splitlines()]
for name, mrr in at_risk:
    if int(mrr) < 1000:
        env.LINEAR.create_issue(title=f"Check in on {name}")
print("done")
"""})]),
                ("Filed tickets.", []),
            ],
            [
                resource("warehouse", ["query"], result=WAREHOUSE, record=calls),
                resource("linear", ["create_issue"], record=calls),
            ],
            code_mode=True,
        )
        agent.run("Flag at-risk accounts")
        assert [c[0] for c in calls] == ["warehouse", "linear", "linear"]
        assert calls[1][1]["title"] == "Check in on northwind"
        # One tool call from the model's perspective, three real operations.
        assert agent.llm.n == 2

    def test_describe_binding_works_in_a_real_run(self) -> None:
        agent = build_agent(
            [
                ("", [("describe_binding", {"name": "WAREHOUSE"})]),
                ("Now I know.", []),
            ],
            [resource("warehouse", ["query", "load"])],
            code_mode=True,
        )
        result = agent.run("What can the warehouse do?")
        described = [m for m in result.messages if m.role == "tool"][0].content
        assert "env.WAREHOUSE" in described
        assert "query" in described and "load" in described


class TestGating:
    """A binding call must be gated exactly like the tool call it wraps."""

    def test_a_denied_binding_call_does_not_run(self) -> None:
        calls: list = []
        agent = build_agent(
            [
                ("", [("execute_code", {"code":
                    'try:\n    env.STRIPE.create_charge(title="x")\n'
                    'except Exception as e:\n    print("blocked:", e)'})]),
                ("Blocked.", []),
            ],
            [resource("stripe", ["create_charge"], record=calls)],
            code_mode=True,
            permissions=PermissionEngine(deny=["stripe"]),
        )
        result = agent.run("charge them")
        assert calls == []  # the tool never ran
        assert "blocked:" in [m for m in result.messages if m.role == "tool"][0].content

    def test_an_env_call_enters_the_approval_queue(self) -> None:
        calls: list = []
        queue = ApprovalQueue()
        agent = build_agent(
            [
                ("", [("execute_code", {"code":
                    'try:\n    env.LINEAR.create_issue(title="ship it")\n'
                    'except Exception as e:\n    print("queued:", e)'})]),
                ("Queued.", []),
            ],
            [resource("linear", ["create_issue"], record=calls)],
            code_mode=True,
            approvals=queue,
            permissions=PermissionEngine(ask=["linear"], allow=["execute_code"]),
        )
        agent.run("file a ticket")

        assert calls == []                      # not run during the turn
        assert len(queue.pending()) == 1        # queued instead
        queue.approve_all(by="rahul")
        assert calls == [("linear", {"action": "create_issue", "title": "ship it"})]

    def test_env_calls_appear_in_the_transcript(self) -> None:
        agent = build_agent(
            [
                ("", [("execute_code", {"code": 'env.WAREHOUSE.query(sql="x")'})]),
                ("done", []),
            ],
            [resource("warehouse", ["query"], result=WAREHOUSE)],
            code_mode=True,
        )
        result = agent.run("query it")
        # Not hidden inside one opaque "ran code" row — the underlying call is
        # emitted like any other.
        called = [e for e in result.events if e.type == "tool_called"]
        assert any(e.payload.get("tool") == "warehouse" for e in called)

    def test_guardrails_apply_to_env_calls(self) -> None:
        from shipit_agent import Guardrails

        calls: list = []
        agent = build_agent(
            [
                ("", [("execute_code", {"code":
                    'try:\n    env.WAREHOUSE.query(sql="DROP TABLE users")\n'
                    'except Exception as e:\n    print("stopped")'})]),
                ("done", []),
            ],
            [resource("warehouse", ["query"], record=calls)],
            code_mode=True,
            guardrails=Guardrails(tool_rules={"warehouse": [r"DROP\s+TABLE"]}),
        )
        agent.run("clean up")
        assert calls == []


class TestFailureModes:
    def test_an_unknown_binding_is_reported_to_the_code(self) -> None:
        agent = build_agent(
            [
                ("", [("execute_code", {"code": "env.NOPE.thing()"})]),
                ("done", []),
            ],
            [resource("warehouse", ["query"])],
            code_mode=True,
        )
        result = agent.run("go")
        assert "No binding named" in [m for m in result.messages if m.role == "tool"][0].content

    def test_an_unknown_method_is_reported(self) -> None:
        agent = build_agent(
            [
                ("", [("execute_code", {"code": "env.WAREHOUSE.drop_everything()"})]),
                ("done", []),
            ],
            [resource("warehouse", ["query"])],
            code_mode=True,
        )
        result = agent.run("go")
        assert "no method" in [m for m in result.messages if m.role == "tool"][0].content

    def test_code_mode_with_no_bindable_tools_is_harmless(self) -> None:
        agent = build_agent([("done", [])], [], code_mode=True)
        assert agent.run("hi").output == "done"

    def test_a_tool_raising_inside_env_surfaces_as_an_error(self) -> None:
        class Broken:
            name = "broken"
            description = "x"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "broken", "parameters": {
                    "properties": {"action": {"type": "string", "enum": ["go"]}}}}}

            def run(self, context, **kwargs):
                raise RuntimeError("upstream exploded")

        agent = build_agent(
            [
                ("", [("execute_code", {"code":
                    'try:\n    env.BROKEN.go()\nexcept Exception as e:\n    print("err:", e)'})]),
                ("done", []),
            ],
            [Broken()],
            code_mode=True,
        )
        result = agent.run("go")
        content = [m for m in result.messages if m.role == "tool"][0].content
        assert "upstream exploded" in content
