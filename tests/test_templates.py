from shipit_agent.templates import PromptTemplate


def test_render_simple_variable():
    t = PromptTemplate(template="Hello {name}")
    assert t.render(name="World") == "Hello World"


def test_render_nested_variable():
    t = PromptTemplate(template="Review PR: {payload.pull_request.title}")
    payload = {"pull_request": {"title": "Fix auth bug"}}
    assert t.render(payload=payload) == "Review PR: Fix auth bug"


def test_render_missing_variable_unchanged():
    t = PromptTemplate(template="Hello {missing}")
    assert t.render(name="World") == "Hello {missing}"


def test_variables_extraction():
    t = PromptTemplate(template="Check {payload.repo} for {payload.event}")
    assert t.variables() == ["payload.repo", "payload.event"]


def test_render_multiple_variables():
    t = PromptTemplate(template="{payload.action} on {payload.repo.name} by {payload.sender.login}")
    payload = {"action": "opened", "repo": {"name": "shipit"}, "sender": {"login": "rahul"}}
    assert t.render(payload=payload) == "opened on shipit by rahul"
