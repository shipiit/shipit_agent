from shipit_agent import (
    Agent,
    FileMemoryStore,
    FileSessionStore,
    InMemoryMemoryStore,
    InMemorySessionStore,
    MemoryTool,
    Message,
    WorkspaceFilesTool,
)
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.models import ToolCall


def test_session_store_persists_messages_between_runs() -> None:
    store = InMemorySessionStore()
    agent = Agent(
        llm=SimpleEchoLLM(), prompt="Prompt", session_store=store, session_id="abc"
    )
    first = agent.run("first")
    second = agent.run("second")
    assert len(second.messages) > len(first.messages)


def test_memory_store_collects_tool_outputs() -> None:
    memory = InMemoryMemoryStore()

    class ToolCallingLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            tool_messages = [m for m in messages if getattr(m, "role", "") == "tool"]
            if tool_messages:
                return LLMResponse(content="done")
            return LLMResponse(
                content="", tool_calls=[ToolCall(name="echo_tool", arguments={})]
            )

    class EchoTool:
        name = "echo_tool"
        description = "Echo tool"
        prompt_instructions = "Use for echo."

        def schema(self) -> dict:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }

        def run(self, context, **kwargs):
            return type(
                "Output", (), {"text": "stored value", "metadata": {"persist": True}}
            )()

    agent = Agent(
        llm=ToolCallingLLM(), prompt="Prompt", tools=[EchoTool()], memory_store=memory
    )
    agent.run("store")
    matches = memory.search("stored")
    assert matches


def test_memory_tool_can_store_and_search() -> None:
    memory_store = InMemoryMemoryStore()
    tool = MemoryTool()
    context = type("Ctx", (), {"state": {"memory_store": memory_store}})()
    tool.run(context=context, action="store", content="User prefers concise replies")
    result = tool.run(context=context, action="search", query="concise")
    assert "concise" in result.text.lower()


def test_workspace_files_tool_roundtrip(tmp_path) -> None:
    tool = WorkspaceFilesTool(root_dir=tmp_path)
    tool.run(context=None, action="write", path="notes.txt", content="hello")  # type: ignore[arg-type]
    result = tool.run(context=None, action="read", path="notes.txt")  # type: ignore[arg-type]
    assert result.text == "hello"


def test_file_memory_store_persists_facts(tmp_path) -> None:
    store = FileMemoryStore(tmp_path / "memory.json")
    store.add(
        type(
            "Fact",
            (),
            {
                "content": "alpha fact",
                "category": "general",
                "score": 1.0,
                "metadata": {},
            },
        )()
    )
    matches = store.search("alpha")
    assert matches
    assert matches[0].content == "alpha fact"


def test_file_session_store_persists_records(tmp_path) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    first_agent = Agent(
        llm=SimpleEchoLLM(), session_store=store, session_id="persisted"
    )
    first_agent.run("hello")

    second_agent = Agent(
        llm=SimpleEchoLLM(), session_store=store, session_id="persisted"
    )
    result = second_agent.run("again")
    assert len(result.messages) > 2


def test_agent_can_start_with_seed_history() -> None:
    agent = Agent(
        llm=SimpleEchoLLM(),
        history=[
            Message(role="user", content="Earlier request"),
            Message(role="assistant", content="Earlier response"),
        ],
    )
    result = agent.run("New request")
    contents = [message.content for message in result.messages]
    assert "Earlier request" in contents
    assert "Earlier response" in contents
