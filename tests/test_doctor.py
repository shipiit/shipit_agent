from pathlib import Path

from shipit_agent import Agent, AgentDoctor, CredentialRecord, InMemoryCredentialStore
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
    assert any(check.name == "llm_provider" and check.status == "pass" for check in report.checks)


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
    connector_check = next(check for check in report.checks if check.name == "connectors")
    assert connector_check.status == "warn"
    assert "credential store" in connector_check.message.lower()


def test_agent_doctor_reports_connected_connector_credentials() -> None:
    store = InMemoryCredentialStore()
    store.set(CredentialRecord(key="gmail", provider="gmail", secrets={"access_token": "x"}))
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[GmailTool(credential_store=store)],
        credential_store=store,
        max_iterations=4,
    )
    report = AgentDoctor(env={}).inspect(agent)
    connector_check = next(check for check in report.checks if check.name == "connectors")
    assert connector_check.status == "pass"
    assert "gmail:gmail" in connector_check.details["connected"]


def test_doctor_report_markdown_contains_sections() -> None:
    agent = Agent(
        llm=SimpleEchoLLM(),
        tools=[FunctionTool.from_callable(lambda: "ok", name="ping")],
    )
    markdown = agent.doctor().to_markdown()
    assert "# SHIPIT Agent Doctor Report" in markdown
    assert "## PASS llm_provider" in markdown
