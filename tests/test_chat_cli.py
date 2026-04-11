"""Tests for the modern multi-agent chat REPL (shipit_agent.chat_cli)."""

from __future__ import annotations


import pytest

from shipit_agent.chat_cli import (
    AGENT_TYPES,
    ChatREPL,
    agent_chat_session,
    agent_tools,
    build_parser,
    make_agent,
)
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.stores import InMemorySessionStore


# ---------------------------------------------------------------------------
# argparse + factories
# ---------------------------------------------------------------------------


def test_build_parser_default_agent_is_deep():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.agent == "deep"
    assert args.provider is None


def test_build_parser_accepts_all_agent_types():
    parser = build_parser()
    for t in AGENT_TYPES:
        args = parser.parse_args(["--agent", t])
        assert args.agent == t


def test_build_parser_rejects_unknown_agent_type():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--agent", "nope"])


def test_make_agent_supports_every_type():
    llm = SimpleEchoLLM()
    for t in ("agent", "deep", "goal", "reflective", "adaptive", "persistent"):
        a = make_agent(t, llm=llm, use_builtins=False)
        assert a is not None


def test_make_agent_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown agent type"):
        make_agent("nope", llm=SimpleEchoLLM())


def test_agent_tools_returns_list_for_deep():
    llm = SimpleEchoLLM()
    deep = make_agent("deep", llm=llm, use_builtins=False)
    tools = agent_tools(deep)
    names = {getattr(t, "name", None) for t in tools}
    assert "plan_task" in names


def test_agent_chat_session_uses_inner_agent_for_deep():
    llm = SimpleEchoLLM()
    deep = make_agent("deep", llm=llm, use_builtins=False)
    chat = agent_chat_session(
        deep, session_id="x", session_store=InMemorySessionStore()
    )
    assert chat is not None
    assert chat.agent is deep.agent


# ---------------------------------------------------------------------------
# REPL command parsing — drive scripted input through the loop
# ---------------------------------------------------------------------------


def _drive(repl: ChatREPL, lines: list[str]) -> tuple[int, list[str]]:
    inputs = iter(lines)
    outputs: list[str] = []

    def input_fn(_prompt: str) -> str:
        try:
            return next(inputs)
        except StopIteration:
            return "/exit"

    def output(*args, **_kwargs) -> None:
        outputs.append(" ".join(str(a) for a in args))

    code = repl.run(input_fn=input_fn, output=output)
    return code, outputs


def _new_repl(agent_type: str = "deep") -> ChatREPL:
    return ChatREPL(
        llm=SimpleEchoLLM(),
        agent_type=agent_type,
        use_builtins=False,
        quiet=True,
    )


def test_repl_help_prints_command_list():
    repl = _new_repl()
    code, out = _drive(repl, ["/help", "/exit"])
    assert code == 0
    joined = "\n".join(out)
    assert "/agent" in joined
    assert "/sources" in joined


def test_repl_exit_returns_zero():
    repl = _new_repl()
    code, _ = _drive(repl, ["/exit"])
    assert code == 0


def test_repl_quit_returns_zero():
    repl = _new_repl()
    code, _ = _drive(repl, ["/quit"])
    assert code == 0


def test_repl_unknown_command_warns_but_continues():
    repl = _new_repl()
    code, out = _drive(repl, ["/nope", "/exit"])
    assert code == 0
    assert any("unknown command" in line for line in out)


def test_repl_agent_command_switches_type():
    repl = _new_repl(agent_type="deep")
    code, out = _drive(repl, ["/agent agent", "/info", "/exit"])
    assert code == 0
    assert repl.agent_type == "agent"
    assert any("agent_type" in line and "agent" in line for line in out)


def test_repl_agent_command_rejects_unknown_type():
    repl = _new_repl()
    code, out = _drive(repl, ["/agent unknown", "/exit"])
    assert code == 0
    assert any("unknown agent type" in line for line in out)


def test_repl_agents_command_lists_all_types():
    repl = _new_repl()
    code, out = _drive(repl, ["/agents", "/exit"])
    joined = "\n".join(out)
    for t in AGENT_TYPES:
        assert t in joined


def test_repl_tools_command_lists_tools():
    repl = _new_repl()
    code, out = _drive(repl, ["/tools", "/exit"])
    joined = "\n".join(out)
    assert "plan_task" in joined


def test_repl_quiet_command_toggles_quiet_flag():
    repl = _new_repl()
    repl.quiet = False
    _drive(repl, ["/quiet", "/exit"])
    assert repl.quiet is True


def test_repl_reset_starts_new_session_id():
    repl = _new_repl()
    original_id = repl.session_id
    _drive(repl, ["/reset", "/exit"])
    assert repl.session_id != original_id


def test_repl_save_and_load_round_trip(tmp_path):
    repl = _new_repl()
    out_path = tmp_path / "chat.json"

    # Send one message so the history has content.
    repl.handle_user_turn("hello", output=lambda *a, **k: None)

    code, out = _drive(repl, [f"/save {out_path}", "/exit"])
    assert code == 0
    assert out_path.exists()

    # Re-load into a fresh REPL.
    repl2 = _new_repl()
    code2, out2 = _drive(repl2, [f"/load {out_path}", "/history", "/exit"])
    assert code2 == 0
    assert any("hello" in line for line in out2)


def test_repl_index_initialises_default_rag(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("Shipit supports Python 3.10+.", encoding="utf-8")

    repl = _new_repl()
    assert repl.rag is None
    _drive(repl, [f"/index {notes}", "/rag", "/exit"])
    assert repl.rag is not None
    assert repl.rag.count() > 0


def test_repl_goal_command_from_plain_agent_switches_to_goal_agent():
    repl = _new_repl(agent_type="agent")
    _drive(repl, ["/goal Build a CLI", "/exit"])
    assert repl.agent_type == "goal"
    assert repl.goal_objective == "Build a CLI"


def test_repl_goal_command_from_deep_keeps_deep_but_records_objective():
    # Deep agents support goals natively via the goal= field, so /goal
    # from a deep REPL records the objective without switching types.
    repl = _new_repl(agent_type="deep")
    _drive(repl, ["/goal Build a CLI", "/exit"])
    assert repl.agent_type == "deep"
    assert repl.goal_objective == "Build a CLI"


def test_repl_reflect_only_applies_to_deep():
    repl = _new_repl(agent_type="agent")
    _drive(repl, ["/reflect on", "/exit"])
    # Refused — only Deep supports reflect.
    assert repl.reflect is False


def test_repl_verify_only_applies_to_deep():
    repl = _new_repl(agent_type="agent")
    _drive(repl, ["/verify on", "/exit"])
    assert repl.verify is False


def test_repl_user_turn_records_assistant_history():
    repl = _new_repl()
    repl.handle_user_turn("hi", output=lambda *a, **k: None)
    history = repl.chat.history()
    user_msgs = [m for m in history if m.role == "user"]
    assert len(user_msgs) >= 1
