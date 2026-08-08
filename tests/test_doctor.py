from shipit_agent import (
    Agent,
    AgentDoctor,
    CredentialRecord,
    InMemoryCredentialStore,
    Skill,
    SkillRegistry,
)
from shipit_agent.doctor import DoctorReport
from shipit_agent.llms import OpenAIChatLLM, SimpleEchoLLM
from shipit_agent.tools import FunctionTool, GmailTool


def test_agent_doctor_passes_for_local_echo_agent() -> None:
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[FunctionTool.from_callable(lambda: "ok", name="ping")],
        max_iterations=4,
    )
    report = agent.doctor()
    assert isinstance(report, DoctorReport)
    assert not report.failures
    assert any(
        check.name == "llm_provider" and check.status == "pass"
        for check in report.checks
    )


def test_agent_doctor_detects_missing_openai_key() -> None:
    agent = Agent(llm=OpenAIChatLLM(model="gpt-4o-mini"))
    report = agent.doctor(env={})
    llm_check = next(check for check in report.checks if check.name == "llm_provider")
    assert llm_check.status == "fail"
    assert "OPENAI_API_KEY" in llm_check.details["missing"]


def test_agent_doctor_warns_for_missing_connector_credentials() -> None:
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[GmailTool()],
        max_iterations=4,
    )
    report = agent.doctor()
    connector_check = next(
        check for check in report.checks if check.name == "connectors"
    )
    assert connector_check.status == "warn"
    assert "credential store" in connector_check.message.lower()


def test_agent_doctor_reports_connected_connector_credentials() -> None:
    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(key="gmail", provider="gmail", secrets={"access_token": "x"})
    )
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[GmailTool(credential_store=store)],
        credential_store=store,
        max_iterations=4,
    )
    report = AgentDoctor(env={}).inspect(agent)
    connector_check = next(
        check for check in report.checks if check.name == "connectors"
    )
    assert connector_check.status == "pass"
    assert "gmail:gmail" in connector_check.details["connected"]


def test_agent_doctor_rejects_an_empty_connector_credential() -> None:
    store = InMemoryCredentialStore()
    store.set(CredentialRecord(key="gmail", provider="gmail", secrets={}))
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[GmailTool(credential_store=store)],
        credential_store=store,
    )

    connector_check = next(
        check for check in agent.doctor().checks if check.name == "connectors"
    )

    assert connector_check.status == "warn"
    assert "gmail:gmail(needs_auth)" in connector_check.details["unavailable"]


def test_doctor_report_markdown_contains_sections() -> None:
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[FunctionTool.from_callable(lambda: "ok", name="ping")],
    )
    markdown = agent.doctor().to_markdown()
    assert "# SHIPIT Agent Doctor Report" in markdown
    assert "## PASS llm_provider" in markdown


def test_doctor_reports_tool_families_and_validates_schemas() -> None:
    agent = Agent.with_builtins(llm=SimpleEchoLLM(), auto_use_skills=False)

    tool_check = next(check for check in agent.doctor().checks if check.name == "tools")

    assert tool_check.status == "pass"
    assert tool_check.details["family_count"] >= 8
    assert "connectors=" in tool_check.details["families"]


def test_doctor_warns_when_active_skill_dependencies_are_missing() -> None:
    skill = Skill(
        id="ops",
        name="Ops",
        tools=["missing_tool"],
        mcps=[{"name": "observability"}],
    )
    registry = SkillRegistry()
    registry.register(skill)
    agent = Agent(
        llm=SimpleEchoLLM(),
        skill_registry=registry,
        skills=[skill],
        auto_use_skills=False,
    )

    skill_check = next(
        check for check in agent.doctor().checks if check.name == "skills"
    )

    assert skill_check.status == "warn"
    assert skill_check.details["missing_tools"] == "ops:missing_tool"
    assert skill_check.details["missing_mcps"] == "ops:observability"


def test_doctor_fails_a_tool_with_an_invalid_schema() -> None:
    class BrokenTool:
        name = "broken"
        description = "Broken schema"

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": "wrong_name",
                    "parameters": {"type": "object"},
                },
            }

    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[BrokenTool()],
        auto_use_skills=False,
    )

    tool_check = next(check for check in agent.doctor().checks if check.name == "tools")

    assert tool_check.status == "fail"
    assert "schema name mismatch" in tool_check.details["invalid"]


def test_optimized_builtin_agent_enables_long_run_token_controls() -> None:
    agent = Agent.with_builtins(
        llm=SimpleEchoLLM(),
        optimized=True,
        auto_use_skills=False,
    )

    efficiency = next(
        check for check in agent.doctor().checks if check.name == "efficiency"
    )

    assert agent.code_mode is True
    assert agent.context_window_tokens == 128_000
    assert agent.max_iterations == 8
    assert agent.max_tool_output_chars == 16_000
    assert efficiency.status == "pass"


def test_optimized_builtin_agent_preserves_explicit_overrides() -> None:
    agent = Agent.with_builtins(
        llm=SimpleEchoLLM(),
        optimized=True,
        code_mode=False,
        context_window_tokens=64_000,
        max_iterations=12,
        max_tool_output_chars=24_000,
        auto_use_skills=False,
    )

    assert agent.code_mode is False
    assert agent.context_window_tokens == 64_000
    assert agent.max_iterations == 12
    assert agent.max_tool_output_chars == 24_000
