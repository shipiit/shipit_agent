import base64
from pathlib import Path
from types import SimpleNamespace

from shipit_agent import (
    get_builtin_tools,
    ConfluenceTool,
    CredentialRecord,
    CustomAPITool,
    FileCredentialStore,
    GmailTool,
    GoogleCalendarTool,
    GoogleDriveTool,
    JiraTool,
    LinearTool,
    NotionTool,
    SlackTool,
)
from shipit_agent.integrations import InMemoryCredentialStore


def test_file_credential_store_roundtrip(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set(
        CredentialRecord(key="gmail", provider="gmail", secrets={"access_token": "x"})
    )
    record = store.get("gmail")
    assert record is not None
    assert record.provider == "gmail"


def test_inmemory_credential_store_lists_records() -> None:
    store = InMemoryCredentialStore()
    store.set(CredentialRecord(key="slack", provider="slack", secrets={"token": "x"}))
    records = store.list()
    assert len(records) == 1
    assert records[0].key == "slack"


def test_gmail_tool_schema_supports_multiple_actions() -> None:
    actions = GmailTool().schema()["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
    assert {
        "search",
        "read_message",
        "read_thread",
        "get_attachment",
        "create_draft",
        "send_message",
    }.issubset(set(actions))


def test_slack_tool_schema_supports_richer_actions() -> None:
    actions = SlackTool().schema()["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
    assert {"channel_history", "get_thread_replies", "user_lookup"}.issubset(
        set(actions)
    )


def test_linear_tool_schema_supports_richer_actions() -> None:
    actions = LinearTool().schema()["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
    assert {"get_issue", "update_issue", "list_teams", "list_projects"}.issubset(
        set(actions)
    )


def test_jira_tool_schema_supports_richer_actions() -> None:
    actions = JiraTool().schema()["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
    assert {
        "get_issue",
        "list_transitions",
        "transition_issue",
        "add_comment",
        "assign_issue",
    }.issubset(set(actions))


def test_connector_tools_return_not_connected_without_credentials() -> None:
    context = type("Ctx", (), {"state": {}})()
    tools = [
        GmailTool(),
        GoogleCalendarTool(),
        GoogleDriveTool(),
        SlackTool(),
        LinearTool(),
        JiraTool(),
        NotionTool(),
        ConfluenceTool(),
        CustomAPITool(),
    ]
    for tool in tools:
        props = tool.schema()["function"]["parameters"]["properties"]
        kwargs = (
            {"action": props["action"]["default"]}
            if "action" in props
            else {"method": "GET", "path": "/health"}
        )
        result = tool.run(context=context, **kwargs)
        assert result.metadata["connected"] is False


def test_builtin_tools_include_connector_tools() -> None:
    names = {tool.name for tool in get_builtin_tools()}
    assert "gmail_search" in names
    assert "google_calendar" in names
    assert "google_drive" in names
    assert "slack" in names
    assert "linear" in names
    assert "jira" in names
    assert "notion" in names
    assert "confluence" in names
    assert "custom_api" in names


def test_gmail_tool_extracts_body_and_attachment_metadata() -> None:
    body_text = base64.urlsafe_b64encode(b"Plain text body").decode("utf-8")
    html_text = base64.urlsafe_b64encode(b"<p>Hello</p>").decode("utf-8")
    tool = GmailTool()
    details = tool._extract_message_content(
        {
            "payload": {
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": body_text}},
                    {"mimeType": "text/html", "body": {"data": html_text}},
                    {
                        "mimeType": "application/pdf",
                        "filename": "invoice.pdf",
                        "body": {"attachmentId": "att-1", "size": 12},
                    },
                ]
            }
        }
    )
    assert details["body_text"] == "Plain text body"
    assert details["body_html"] == "<p>Hello</p>"
    assert details["attachments"][0]["attachment_id"] == "att-1"


def test_gmail_tool_read_message_includes_full_body_and_attachments() -> None:
    class _Execute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class FakeMessages:
        def __init__(self, payload):
            self.payload = payload

        def get(self, **kwargs):
            return _Execute(self.payload)

        def attachments(self):
            raise AssertionError("attachments() should not be used in this test")

    class FakeUsers:
        def __init__(self, payload):
            self.payload = payload

        def messages(self):
            return FakeMessages(self.payload)

    class FakeService:
        def __init__(self, payload):
            self.payload = payload

        def users(self):
            return FakeUsers(self.payload)

    class FakeGmailTool(GmailTool):
        def _build_service(self, record):
            return FakeService(
                {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "Plain text body",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Hello"},
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "To", "value": "receiver@example.com"},
                            {"name": "Date", "value": "Thu, 1 Jan 2026 10:00:00 +0000"},
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {
                                    "data": base64.urlsafe_b64encode(
                                        b"Plain text body"
                                    ).decode("utf-8")
                                },
                            },
                            {
                                "mimeType": "application/pdf",
                                "filename": "invoice.pdf",
                                "body": {"attachmentId": "att-1", "size": 24},
                            },
                        ],
                    },
                }
            )

    store = InMemoryCredentialStore()
    store.set(
        CredentialRecord(key="gmail", provider="gmail", secrets={"access_token": "x"})
    )
    tool = FakeGmailTool(credential_store=store)
    context = SimpleNamespace(state={})
    result = tool.run(context=context, action="read_message", message_id="m1")
    assert "Body:\nPlain text body" in result.text
    assert "invoice.pdf" in result.text
    assert result.metadata["item"]["attachments"][0]["attachment_id"] == "att-1"


def test_slack_tool_supports_history_replies_and_user_lookup() -> None:
    class FakeSlackTool(SlackTool):
        def _get_record(self, context):
            return object()

        def _request_json(self, *, record, method, path, query=None, body=None):
            if path == "/conversations.history":
                return {
                    "ok": True,
                    "messages": [{"user": "U1", "text": "hello history", "ts": "1.0"}],
                }
            if path == "/conversations.replies":
                return {
                    "ok": True,
                    "messages": [
                        {
                            "user": "U2",
                            "text": "thread reply",
                            "ts": "2.0",
                            "thread_ts": "1.0",
                        }
                    ],
                }
            if path == "/users.lookupByEmail":
                return {
                    "ok": True,
                    "user": {
                        "id": "U3",
                        "real_name": "Ada Lovelace",
                        "profile": {"email": "ada@example.com"},
                    },
                }
            raise AssertionError(path)

    tool = FakeSlackTool()
    context = SimpleNamespace(state={})
    history = tool.run(context=context, action="channel_history", channel="C1")
    replies = tool.run(
        context=context, action="get_thread_replies", channel="C1", thread_ts="1.0"
    )
    user = tool.run(context=context, action="user_lookup", email="ada@example.com")
    assert "hello history" in history.text
    assert "thread reply" in replies.text
    assert "Ada Lovelace" in user.text


def test_linear_tool_supports_team_project_get_and_update_actions() -> None:
    class FakeLinearTool(LinearTool):
        def _get_record(self, context):
            return object()

        def _request_json(self, *, record, method, path, query=None, body=None):
            query_text = body["query"]
            if "ListTeams" in query_text:
                return {
                    "data": {
                        "teams": {
                            "nodes": [{"id": "t1", "key": "ENG", "name": "Engineering"}]
                        }
                    }
                }
            if "ListProjects" in query_text:
                return {
                    "data": {
                        "projects": {
                            "nodes": [
                                {
                                    "id": "p1",
                                    "name": "Shipit",
                                    "slug": "shipit",
                                    "state": "planned",
                                    "color": "#000",
                                }
                            ]
                        }
                    }
                }
            if "GetIssue" in query_text:
                return {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "i1",
                                    "identifier": "ENG-12",
                                    "title": "Bug",
                                    "priority": 2,
                                    "state": {"id": "s1", "name": "Todo"},
                                    "assignee": {"id": "u1", "name": "Rahul"},
                                    "project": {"id": "p1", "name": "Shipit"},
                                }
                            ]
                        }
                    }
                }
            if "UpdateIssue" in query_text:
                return {
                    "data": {
                        "issueUpdate": {
                            "issue": {
                                "id": "i1",
                                "identifier": "ENG-12",
                                "title": "Renamed bug",
                            }
                        }
                    }
                }
            raise AssertionError(query_text)

    tool = FakeLinearTool()
    context = SimpleNamespace(state={})
    teams = tool.run(context=context, action="list_teams")
    projects = tool.run(context=context, action="list_projects")
    issue = tool.run(context=context, action="get_issue", identifier="ENG-12")
    updated = tool.run(
        context=context, action="update_issue", issue_id="i1", title="Renamed bug"
    )
    assert "Engineering" in teams.text
    assert "Shipit" in projects.text
    assert "ENG-12" in issue.text
    assert "Renamed bug" in updated.text


def test_jira_tool_supports_transition_comment_assign_and_get() -> None:
    class FakeJiraTool(JiraTool):
        def _get_record(self, context):
            return object()

        def _request_json(self, *, record, method, path, query=None, body=None):
            if path.endswith("/transitions") and method == "GET":
                return {"transitions": [{"id": "31", "name": "Done"}]}
            if path.endswith("/transitions") and method == "POST":
                return {"ok": True}
            if path.endswith("/comment"):
                return {"id": "c1"}
            if path.endswith("/assignee"):
                return {"ok": True}
            if "/issue/PROJ-7" in path and method == "GET":
                return {
                    "key": "PROJ-7",
                    "fields": {
                        "summary": "Bug",
                        "status": {"name": "In Progress"},
                        "assignee": {"displayName": "Rahul"},
                    },
                }
            raise AssertionError((method, path))

    tool = FakeJiraTool()
    context = SimpleNamespace(state={})
    issue = tool.run(context=context, action="get_issue", issue_key="PROJ-7")
    transitions = tool.run(
        context=context, action="list_transitions", issue_key="PROJ-7"
    )
    transitioned = tool.run(
        context=context,
        action="transition_issue",
        issue_key="PROJ-7",
        transition_id="31",
    )
    commented = tool.run(
        context=context, action="add_comment", issue_key="PROJ-7", comment_body="done"
    )
    assigned = tool.run(
        context=context, action="assign_issue", issue_key="PROJ-7", account_id="acct-1"
    )
    assert "PROJ-7" in issue.text
    assert "Done" in transitions.text
    assert "31" in transitioned.text
    assert "Comment added" in commented.text
    assert "acct-1" in assigned.text
