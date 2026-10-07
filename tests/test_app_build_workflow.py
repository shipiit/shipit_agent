"""Real local tools/subprocesses, scripted model: build, fail, patch, verify."""
import pytest

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.file_write import FileWriteTool
from shipit_agent.tools.file_read import FileReadTool
from shipit_agent.tools.edit_file import EditFileTool
from shipit_agent.tools.code_execution import CodeExecutionTool


@pytest.mark.parametrize("streaming", [False, True])
def test_build_and_repair_small_wsgi_application(tmp_path, streaming):
    app = ('def application(environ, start_response):\n'
           '    start_response("500 Internal Server Error", [("Content-Type", "text/plain")])\n'
           '    return [b"Hello Shipit"]\n')
    check = ('import runpy\n'
             'app = runpy.run_path("app.py")["application"]\n'
             'statuses = []\n'
             'body = app({}, lambda status, headers: statuses.append(status))\n'
             'assert statuses == ["200 OK"], statuses\n'
             'assert body == [b"Hello Shipit"]\n'
             'print("APP_CHECK_PASSED")\n')
    steps = [
        ("write_file", {"path": "app.py", "content": app}),
        ("read_file", {"path": "app.py"}),
        ("run_code", {"language": "python", "code": check}),
        ("edit_file", {"path": "app.py", "old_text": "500 Internal Server Error", "new_text": "200 OK"}),
        ("run_code", {"language": "python", "code": check}),
    ]
    class Model:
        calls = 0
        def complete(self, *, messages, **kwargs):
            index = self.calls
            self.calls += 1
            if index == 3:
                assert any(m.role == "tool" and "AssertionError" in m.content for m in messages)
            if index == len(steps):
                assert any(m.role == "tool" and "APP_CHECK_PASSED" in m.content for m in messages)
                return LLMResponse(content="Created and verified the application.")
            name, arguments = steps[index]
            return LLMResponse(tool_calls=[ToolCall(name=name, arguments=arguments, id=f"step-{index}")])
    model = Model()
    agent = Agent(llm=model, tools=[
        FileWriteTool(root_dir=tmp_path), FileReadTool(root_dir=tmp_path),
        EditFileTool(root_dir=tmp_path), CodeExecutionTool(workspace_root=tmp_path),
    ], auto_use_skills=False, auto_project_memory=False, auto_project_skills=False)
    if streaming:
        events = list(agent.stream("Build and test a small greeting application."))
        assert any(e.type == "run_completed" for e in events)
    else:
        assert agent.run("Build and test a small greeting application.").output == "Created and verified the application."
    assert model.calls == 6
    assert "200 OK" in (tmp_path / "app.py").read_text()
    assert "500 Internal Server Error" not in (tmp_path / "app.py").read_text()
