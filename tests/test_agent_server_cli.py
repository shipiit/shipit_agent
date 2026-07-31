"""Tests for AgentServer (OpenAI-compatible) and the `shipit` CLI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.serve import AgentServer


class EchoBackLLM:
    def complete(self, *, messages, tools=None, text_delta_callback=None, **_kw):
        last = next(m for m in reversed(messages)
                    if (m.get("role") if isinstance(m, dict) else m.role) == "user")
        text = last.get("content") if isinstance(last, dict) else last.content
        answer = f"echo: {text}"
        if text_delta_callback:
            for token in answer.split(" "):
                text_delta_callback(token + " ")
        return LLMResponse(content=answer)


@pytest.fixture()
def server():
    agent = Agent(llm=EchoBackLLM(), auto_use_skills=False)
    srv = AgentServer(agent, model_name="shipit-test", api_key="sekrit")
    port = srv.start(port=0)
    yield f"http://127.0.0.1:{port}", srv
    srv.stop()


def _post(base, path, body, key="sekrit"):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode()


class TestAgentServer:
    def test_chat_completion(self, server) -> None:
        base, _ = server
        status, body = _post(base, "/v1/chat/completions",
                             {"model": "shipit-test",
                              "messages": [{"role": "user", "content": "hi there"}]})
        assert status == 200
        data = json.loads(body)
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "echo: hi there"

    def test_streaming_sse(self, server) -> None:
        base, _ = server
        req = urllib.request.Request(
            base + "/v1/chat/completions",
            data=json.dumps({"stream": True,
                             "messages": [{"role": "user", "content": "stream me"}]}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer sekrit"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.headers["Content-Type"].startswith("text/event-stream")
            raw = resp.read().decode()
        chunks = [json.loads(line[6:]) for line in raw.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
        assert "echo: stream me" in text
        assert raw.strip().endswith("data: [DONE]")
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"

    def test_auth_required(self, server) -> None:
        base, _ = server
        with pytest.raises(urllib.error.HTTPError) as err:
            _post(base, "/v1/chat/completions",
                  {"messages": [{"role": "user", "content": "x"}]}, key="wrong")
        assert err.value.code == 401

    def test_validation_before_work(self, server) -> None:
        base, _ = server
        with pytest.raises(urllib.error.HTTPError) as err:
            _post(base, "/v1/chat/completions", {"messages": []})
        assert err.value.code == 400

    def test_models_and_health(self, server) -> None:
        base, _ = server
        req = urllib.request.Request(base + "/v1/models",
                                     headers={"Authorization": "Bearer sekrit"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            models = json.loads(resp.read())
        assert models["data"][0]["id"] == "shipit-test"
        with urllib.request.urlopen(base + "/health", timeout=10) as resp:
            assert json.loads(resp.read())["status"] == "ok"

    def test_content_block_messages(self, server) -> None:
        base, _ = server
        status, body = _post(base, "/v1/chat/completions",
                             {"messages": [{"role": "user", "content": [
                                 {"type": "text", "text": "blocks work"}]}]})
        assert json.loads(body)["choices"][0]["message"]["content"] == "echo: blocks work"


class TestShipitCLI:
    def test_roles_lists_specialists(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["roles"]) == 0
        out = capsys.readouterr().out
        assert "finance-analyst" in out and "Finance" in out

    def test_mcp_lists_catalog(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["mcp"]) == 0
        out = capsys.readouterr().out
        assert "filesystem" in out and "github" in out

    def test_tools_lists_builtins(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["tools"]) == 0
        out = capsys.readouterr().out
        assert "deep_research" in out and "build_document" in out

    def test_version(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["version"]) == 0
        assert capsys.readouterr().out.strip()

    def test_run_echo_json(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["run", "hello world", "--provider", "echo", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert "output" in data and "summary" in data

    def test_unknown_provider_exits(self) -> None:
        from shipit_agent.cli import build_llm

        with pytest.raises(SystemExit):
            build_llm("not-a-provider")

    def test_help_without_command(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main([]) == 0
        assert "serve" in capsys.readouterr().out


class TestCodeCommand:
    def test_code_registered_with_modes(self, capsys) -> None:
        from shipit_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["code", "fix the bug", "--plan"])
        assert args.task == "fix the bug" and args.plan is True
        args2 = parser.parse_args(["code", "rename x", "--yes",
                                   "--guardrails", "strict"])
        assert args2.yes and args2.guardrails == "strict"

    def test_code_runs_with_echo_provider(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(tmp_path)
        from shipit_agent.cli import main

        assert main(["code", "say hello", "--provider", "echo", "--yes"]) == 0
        out = capsys.readouterr().out
        assert "shipit code" in out          # banner
        assert str(tmp_path) in out          # repo row


class TestUIKit:
    def test_no_color_env_wins(self, monkeypatch) -> None:
        from shipit_agent.cli import ui

        monkeypatch.setenv("NO_COLOR", "1")
        assert ui.style("x", "title") == "x"
        monkeypatch.delenv("NO_COLOR")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert "\033[" in ui.style("x", "title")


class TestModelsCommand:
    def test_models_lists_latest_per_provider(self, capsys) -> None:
        from shipit_agent.cli import main

        assert main(["models"]) == 0
        out = capsys.readouterr().out
        assert "claude-opus-5" in out
        assert "gpt-5.5" in out and "gpt-5.6" in out
        assert "google.gemma-4-31b" in out
        assert "→" in out  # default marker

    def test_defaults_are_in_catalog(self) -> None:
        from shipit_agent.cli.llm import DEFAULT_MODELS, MODEL_CATALOG

        for provider, default in DEFAULT_MODELS.items():
            ids = [m for m, _ in MODEL_CATALOG.get(provider, [])]
            assert default in ids, (provider, default)
