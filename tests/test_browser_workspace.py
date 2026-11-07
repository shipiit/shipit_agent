import pytest

from shipit_agent.browser_workspace import WorkspaceTool
from shipit_agent.tools.base import ToolContext


class Google:
    connected = True

    def __init__(self):
        self.calls = []
        self.document = {"revisionId": "revision-1", "title": "Project"}

    def request(self, method, url, body=None):
        self.calls.append((method, url, body))
        if method == "GET":
            return dict(self.document)
        return {"documentId": "document123", "replies": [{}]}


def propose(tool, service="docs"):
    return tool.run(
        ToolContext(prompt="Update this document"),
        action="propose_update",
        service=service,
        file_id="document123",
        requests=[
            {"insertText": {"endOfSegmentLocation": {}, "text": "Approved content"}}
        ],
    )


def test_proposal_does_not_write_and_apply_uses_exact_revision():
    client = Google()
    tool = WorkspaceTool(client)
    assert propose(tool).metadata["ok"]
    assert [call[0] for call in client.calls] == ["GET"]
    proposal = tool.public_proposals()[0]
    assert "url" not in proposal and "before" not in proposal
    assert proposal["body"]["writeControl"] == {"requiredRevisionId": "revision-1"}
    result = tool.apply(proposal["id"], True)
    assert result["status"] == "applied"
    assert (
        client.calls[-1][1]
        == "https://docs.googleapis.com/v1/documents/document123:batchUpdate"
    )
    with pytest.raises(ValueError, match="resolved"):
        tool.apply(proposal["id"], True)


def test_dismiss_never_writes():
    client = Google()
    tool = WorkspaceTool(client)
    propose(tool)
    tool.apply(tool.public_proposals()[0]["id"], False)
    assert [call[0] for call in client.calls] == ["GET"]


def test_missing_revision_blocks_doc_edit():
    client = Google()
    client.document = {"title": "Project"}
    tool = WorkspaceTool(client)
    assert propose(tool).metadata["ok"] is False
    assert tool.public_proposals() == []


def test_sheets_changed_before_apply_is_rejected():
    client = Google()
    tool = WorkspaceTool(client)
    tool.run(
        ToolContext(prompt="Edit"),
        action="propose_values",
        service="sheets",
        file_id="sheet123",
        range="Sheet1!A1",
        values=[[42]],
    )
    client.document = {"values": [[99]]}
    with pytest.raises(ValueError, match="changed"):
        tool.apply(tool.public_proposals()[0]["id"], True)
    assert all(call[0] == "GET" for call in client.calls)


def test_failed_write_is_not_replayed():
    class Fails(Google):
        def request(self, method, url, body=None):
            if method != "GET":
                self.calls.append((method, url, body))
                raise OSError("lost response")
            return super().request(method, url, body)

    client = Fails()
    tool = WorkspaceTool(client)
    propose(tool)
    pid = tool.public_proposals()[0]["id"]
    with pytest.raises(ValueError, match="unknown"):
        tool.apply(pid, True)
    with pytest.raises(ValueError, match="resolved"):
        tool.apply(pid, True)
    assert sum(call[0] == "POST" for call in client.calls) == 1


def test_session_tools_do_not_share_proposals():
    client = Google()
    a, b = WorkspaceTool(client), WorkspaceTool(client)
    propose(a)
    assert len(a.public_proposals()) == 1 and b.public_proposals() == []


def test_creation_is_also_staged():
    client = Google()
    tool = WorkspaceTool(client)
    tool.run(
        ToolContext(prompt="Create"),
        action="propose_create",
        service="slides",
        title="Weekly briefing",
    )
    assert client.calls == []
    pid = tool.public_proposals()[0]["id"]
    tool.apply(pid, True)
    assert client.calls[-1] == (
        "POST",
        "https://slides.googleapis.com/v1/presentations",
        {"title": "Weekly briefing"},
    )


def test_invalid_approval_does_not_consume_or_write_proposal():
    client = Google()
    tool = WorkspaceTool(client)
    propose(tool)
    pid = tool.public_proposals()[0]["id"]
    for identifier, approve in [([], True), (pid, "yes")]:
        with pytest.raises(ValueError):
            tool.apply(identifier, approve)
    assert tool.public_proposals()[0]["id"] == pid
    assert all(call[0] == "GET" for call in client.calls)
