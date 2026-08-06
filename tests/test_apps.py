"""Apps — what the agent builds once and uses again."""

from __future__ import annotations

import json

import pytest

from shipit_agent.apps import (
    BLUEPRINTS,
    AppStore,
    run_app,
    validate_name,
)
from shipit_agent.tools.apps import app_tools
from shipit_agent.tools.base import ToolContext


@pytest.fixture
def store(tmp_path) -> AppStore:
    return AppStore(tmp_path / "apps")


@pytest.fixture
def tools(store):
    return {tool.name: tool for tool in app_tools(store)}


def ctx(**state) -> ToolContext:
    return ToolContext(prompt="", state=state)


ECHO = '''
def run(input, env):
    return {"echoed": input.get("value")}
'''


class TestStore:
    def test_create_from_a_blueprint(self, store) -> None:
        app = store.create("weekly", title="Weekly report", blueprint="report")
        assert app.entrypoint.exists()
        assert app.manifest.blueprint == "report"
        assert "app.py" in app.files()

    def test_create_from_code(self, store) -> None:
        app = store.create("echo", title="Echo", files={"app.py": ECHO})
        assert "def run(input, env)" in app.entrypoint.read_text()

    def test_code_overrides_the_blueprint(self, store) -> None:
        app = store.create("echo", title="Echo", blueprint="report",
                           files={"app.py": ECHO})
        assert "echoed" in app.entrypoint.read_text()

    def test_an_app_needs_an_entrypoint(self, store) -> None:
        with pytest.raises(ValueError, match="app.py"):
            store.create("empty", title="Empty", files={"notes.md": "hi"})

    def test_names_are_validated_once_and_early(self) -> None:
        for bad in ("", "A", "1st", "has space", "x" * 60, "has-dash"):
            with pytest.raises(ValueError):
                validate_name(bad)
        assert validate_name("rsvp_report") == "rsvp_report"

    def test_creating_twice_is_refused(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        with pytest.raises(FileExistsError):
            store.create("echo", title="Echo", files={"app.py": ECHO})

    def test_overwrite_is_explicit(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        app = store.create("echo", title="Echo 2", files={"app.py": ECHO},
                           overwrite=True)
        assert app.manifest.title == "Echo 2"

    def test_an_unknown_blueprint_names_the_real_ones(self, store) -> None:
        with pytest.raises(KeyError, match="report"):
            store.create("xx", title="X", blueprint="nope")

    def test_apps_survive_the_process(self, tmp_path) -> None:
        AppStore(tmp_path).create("echo", title="Echo", files={"app.py": ECHO})
        # A fresh store over the same directory sees it — an app outlives the
        # run that wrote it, which is the whole point.
        assert AppStore(tmp_path).get("echo").manifest.title == "Echo"

    def test_listing(self, store) -> None:
        store.create("a_app", title="A", files={"app.py": ECHO})
        store.create("b_app", title="B", files={"app.py": ECHO})
        assert [a.name for a in store.list()] == ["a_app", "b_app"]

    def test_delete(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        store.delete("echo")
        assert store.list() == []


class TestBindings:
    def test_wiring_is_recorded_in_the_manifest(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        app = store.bind("echo", source="SHEETS")
        assert app.manifest.bindings == {"SHEETS": "SHEETS"}
        assert store.get("echo").manifest.bindings == {"SHEETS": "SHEETS"}

    def test_it_can_be_renamed_inside_the_app(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        app = store.bind("echo", source="GOOGLE_SHEETS", as_name="SHEET")
        assert app.manifest.bindings == {"SHEET": "GOOGLE_SHEETS"}

    def test_unwiring(self, store) -> None:
        store.create("echo", title="Echo", files={"app.py": ECHO})
        store.bind("echo", source="SHEETS")
        assert store.unbind("echo", "SHEETS").manifest.bindings == {}


class TestRunning:
    def test_the_return_value_comes_back(self, store) -> None:
        app = store.create("echo", title="Echo", files={"app.py": ECHO})
        result = run_app(app, {"value": 42})
        assert result.ok and result.value == {"echoed": 42}

    def test_stdout_is_captured_separately(self, store) -> None:
        app = store.create("noisy", title="Noisy", files={"app.py": '''
def run(input, env):
    print("working")
    return {"done": True}
'''})
        result = run_app(app)
        assert result.value == {"done": True}
        assert "working" in result.stdout

    def test_a_crash_is_reported_not_raised(self, store) -> None:
        app = store.create("bad", title="Bad", files={"app.py": '''
def run(input, env):
    raise ValueError("nope")
'''})
        result = run_app(app)
        assert not result.ok
        assert "ValueError" in result.error and "nope" in result.error

    def test_a_missing_run_function_is_a_clear_error(self, store) -> None:
        app = store.create("bad", title="Bad", files={"app.py": "x = 1\n"})
        result = run_app(app)
        assert not result.ok and "run(input, env)" in result.error

    def test_a_runaway_app_is_stopped(self, store) -> None:
        app = store.create("slow", title="Slow", files={"app.py": '''
import time


def run(input, env):
    time.sleep(30)
'''})
        result = run_app(app, timeout_seconds=1)
        assert result.timed_out and not result.ok

    def test_an_unserializable_return_still_comes_back(self, store) -> None:
        app = store.create("obj", title="Obj", files={"app.py": '''
def run(input, env):
    return object()
'''})
        assert run_app(app).ok

    def test_the_blueprints_all_run(self, store) -> None:
        cases = {
            "report": {"rows": [{"a": 1, "b": 2}]},
            "csv_summary": None,       # needs a path; checked below
            "page": {"rows": [{"a": 1}], "title": "T"},
        }
        for blueprint, payload in cases.items():
            if payload is None:
                continue
            app = store.create(f"bp_{blueprint}", title=blueprint,
                               blueprint=blueprint)
            result = run_app(app, payload)
            assert result.ok, f"{blueprint}: {result.error}"

    def test_the_csv_blueprint_reads_a_real_file(self, store, tmp_path) -> None:
        csv_path = tmp_path / "guests.csv"
        csv_path.write_text("name,status\nDana,confirmed\nSam,maybe\n")
        app = store.create("summary", title="Summary", blueprint="csv_summary")
        result = run_app(app, {"path": str(csv_path), "group_by": "status"})
        assert result.value["rows"] == 2
        assert result.value["counts"] == {"confirmed": 1, "maybe": 1}

    def test_the_page_blueprint_writes_a_file(self, store) -> None:
        app = store.create("page", title="Page", blueprint="page")
        result = run_app(app, {"rows": [{"a": 1}], "title": "Q2"})
        from pathlib import Path

        written = Path(result.value["path"])
        assert written.exists() and "Q2" in written.read_text()


class TestAuthority:
    """An app is never more privileged than the agent that wrote it."""

    def test_an_app_only_sees_bindings_it_was_wired(self, store) -> None:
        store.create("peek", title="Peek", files={"app.py": '''
def run(input, env):
    return sorted(dir(env))
'''})
        store.bind("peek", source="ALLOWED")
        calls = []

        def invoker(binding, method, kwargs):
            # The bridge's handler contract: (text, metadata).
            calls.append((binding, method))
            return "ok", {}

        class FakeBinding:
            methods = {"call": None}

        result = run_app(
            store.get("peek"),
            invoker=invoker,
            bindings={"ALLOWED": FakeBinding(), "SECRET": FakeBinding()},
        )
        assert "ALLOWED" in result.value
        assert "SECRET" not in result.value, "an app must not see what it was not wired"

    def test_env_calls_go_through_the_parent(self, store) -> None:
        store.create("caller", title="Caller", files={"app.py": '''
def run(input, env):
    return env.DATA.call(query="select 1")
'''})
        store.bind("caller", source="DATA")
        seen = []

        def invoker(binding, method, kwargs):
            seen.append((binding, method, kwargs))
            return "42", {}

        class FakeBinding:
            methods = {"call": None}

        result = run_app(store.get("caller"), invoker=invoker,
                         bindings={"DATA": FakeBinding()})
        assert result.ok, result.error
        assert seen and seen[0][0] == "DATA"
        assert seen[0][2] == {"query": "select 1"}
        assert result.env_calls == 1

    def test_an_app_runs_without_a_gate_but_with_no_env(self, store) -> None:
        """No invoker is not an error — it is an app with no resources."""
        app = store.create("plain", title="Plain", files={"app.py": ECHO})
        assert run_app(app, {"value": 1}).ok


class TestTools:
    def test_list_blueprints_names_them(self, tools) -> None:
        text = tools["list_blueprints"].run(ctx()).text
        for blueprint in BLUEPRINTS:
            assert blueprint in text

    def test_create_then_use(self, tools) -> None:
        tools["create_app"].run(ctx(), name="weekly", title="Weekly",
                                blueprint="report")
        out = tools["use_app"].run(
            ctx(), app="weekly", input={"rows": [{"name": "Dana"}]}
        )
        assert out.metadata["ok"]
        assert "Dana" in out.text

    def test_create_reports_what_the_blueprint_brought(self, tools) -> None:
        out = tools["create_app"].run(ctx(), name="weekly", title="Weekly",
                                      blueprint="report")
        assert "app.py" in out.text
        assert out.metadata["app"] == "weekly"

    def test_use_accepts_a_json_string_for_input(self, tools) -> None:
        """Small models send objects as strings; that must not be an error."""
        tools["create_app"].run(ctx(), name="echo", title="Echo",
                                blueprint="report")
        out = tools["use_app"].run(
            ctx(), app="echo", input=json.dumps({"rows": [{"x": 1}]})
        )
        assert out.metadata["ok"]

    def test_an_unknown_app_lists_the_real_ones(self, tools) -> None:
        tools["create_app"].run(ctx(), name="weekly", title="Weekly",
                                blueprint="report")
        out = tools["use_app"].run(ctx(), app="nope")
        assert "weekly" in out.text
        assert out.metadata["error"] == "unknown_app"

    def test_a_failing_app_reports_rather_than_raises(self, tools) -> None:
        tools["create_app"].run(ctx(), name="bad", title="Bad",
                                code="def run(input, env):\n    raise ValueError('x')\n")
        out = tools["use_app"].run(ctx(), app="bad")
        assert not out.metadata["ok"]
        assert "ValueError" in out.text

    def test_binding_an_unknown_name_is_refused(self, tools) -> None:
        tools["create_app"].run(ctx(), name="weekly", title="Weekly",
                                blueprint="report")
        out = tools["set_app_binding"].run(
            ctx(codemode_bindings={"SHEETS": object()}), app="weekly", source="NOPE"
        )
        assert out.metadata["error"] == "unknown_binding"
        assert "SHEETS" in out.text

    def test_binding_is_recorded_and_shown(self, tools) -> None:
        tools["create_app"].run(ctx(), name="weekly", title="Weekly",
                                blueprint="report")
        out = tools["set_app_binding"].run(
            ctx(codemode_bindings={"SHEETS": object()}), app="weekly",
            source="SHEETS"
        )
        assert "SHEETS" in out.text
        assert out.metadata["binding"] == "SHEETS"

    def test_a_bad_name_is_refused_with_the_rule(self, tools) -> None:
        out = tools["create_app"].run(ctx(), name="Not Valid", title="X",
                                      code=ECHO)
        assert out.metadata["error"] == "create_failed"
        assert "snake case" in out.text


class TestNarration:
    def test_the_transcript_says_used_the_app(self) -> None:
        from shipit_agent.narrate import summarize

        assert summarize("use_app", {"app": "weekly"}).past_label().startswith(
            "Used the app"
        )
        assert "Built the app" in summarize(
            "create_app", {"name": "weekly"}
        ).past_label()

    def test_contracts_match_what_the_tools_do(self) -> None:
        from shipit_agent.tools.contracts import CONTRACTS

        assert CONTRACTS["list_blueprints"].read_only
        # Running an app is running code the model wrote.
        assert CONTRACTS["use_app"].destructive
        assert not CONTRACTS["use_app"].auto_approvable
        assert CONTRACTS["use_app"].await_decision
        # Creating one writes files, and the agent waits for the outcome.
        assert CONTRACTS["create_app"].is_action


class TestBuiltins:
    def test_the_app_tools_ship_by_default(self, tmp_path) -> None:
        from shipit_agent.builtins import get_builtin_tool_map

        tools = get_builtin_tool_map(llm=None, project_root=str(tmp_path))
        for name in ("create_app", "use_app", "set_app_binding", "list_blueprints"):
            assert name in tools

    def test_they_share_one_store_under_the_project(self, tmp_path) -> None:
        from shipit_agent.builtins import get_builtin_tool_map

        tools = get_builtin_tool_map(llm=None, project_root=str(tmp_path))
        tools["create_app"].run(ctx(), name="weekly", title="W",
                                blueprint="report")
        out = tools["use_app"].run(ctx(), app="weekly", input={"rows": []})
        assert out.metadata["ok"]
        assert (tmp_path / ".shipit" / "apps" / "weekly" / "app.py").exists()


class TestWorkingDirectory:
    """An app runs where the agent works, not where the app is installed."""

    READS_CWD = '''
from pathlib import Path


def run(input, env):
    return {"found": Path(input["path"]).exists(), "cwd": str(Path.cwd())}
'''

    def test_a_relative_path_resolves_against_the_project(self, tmp_path) -> None:
        (tmp_path / "guests.csv").write_text("name\nDana\n")
        store = AppStore(tmp_path / ".shipit" / "apps")
        store.create("peek", title="Peek", files={"app.py": self.READS_CWD})
        tools = {t.name: t for t in app_tools(store)}
        out = tools["use_app"].run(ctx(), app="peek", input={"path": "guests.csv"})
        assert out.metadata["value"]["found"], (
            "an app given a relative path must resolve it where the agent works"
        )

    def test_the_project_root_is_inferred_from_the_store(self, tmp_path) -> None:
        assert AppStore(tmp_path / ".shipit" / "apps").workdir == tmp_path

    def test_it_can_be_set_explicitly(self, tmp_path) -> None:
        assert AppStore(tmp_path / "apps", workdir=tmp_path).workdir == tmp_path


def test_the_csv_blueprint_accepts_either_argument_name(tmp_path) -> None:
    """`group_by` is documented; `column` is what a model often sends."""
    csv_path = tmp_path / "g.csv"
    csv_path.write_text("name,status\nDana,confirmed\nSam,maybe\n")
    store = AppStore(tmp_path / "apps")
    app = store.create("summary_app", title="S", blueprint="csv_summary")
    for key in ("group_by", "column"):
        result = run_app(app, {"path": str(csv_path), key: "status"})
        assert result.value["counts"] == {"confirmed": 1, "maybe": 1}


class TestFailureIsInformative:
    def test_a_failed_run_shows_what_the_app_expects(self, tools) -> None:
        tools["create_app"].run(ctx(), name="strict", title="Strict", code='''
"""Expects: path (str) — the CSV to read."""


def run(input, env):
    return {"path": input["path"]}
''')
        out = tools["use_app"].run(ctx(), app="strict", input={"wrong": 1})
        assert "Expects: path" in out.text, (
            "a KeyError without the app's own description costs a blind retry"
        )

    def test_the_csv_blueprint_takes_path_file_or_csv(self, tmp_path) -> None:
        csv_path = tmp_path / "g.csv"
        csv_path.write_text("name,status\nDana,confirmed\n")
        store = AppStore(tmp_path / "apps")
        app = store.create("flex", title="Flex", blueprint="csv_summary")
        for key in ("path", "file", "csv"):
            assert run_app(app, {key: str(csv_path)}).ok, key

    def test_no_location_at_all_says_so(self, tmp_path) -> None:
        store = AppStore(tmp_path / "apps")
        app = store.create("flex", title="Flex", blueprint="csv_summary")
        result = run_app(app, {})
        assert not result.ok and "`path`" in result.error


class TestStoreRun:
    """`store.run()` exists because `run_app()` alone gets the cwd wrong."""

    READS = '''
from pathlib import Path


def run(input, env):
    return {"found": Path(input["path"]).exists()}
'''

    def test_it_runs_where_the_agent_works(self, tmp_path) -> None:
        (tmp_path / "data.csv").write_text("a\n1\n")
        store = AppStore(tmp_path / ".shipit" / "apps")
        store.create("peek", title="Peek", files={"app.py": self.READS})
        assert store.run("peek", {"path": "data.csv"}).value["found"]

    def test_run_app_alone_still_defaults_to_the_app_directory(self, tmp_path) -> None:
        (tmp_path / "data.csv").write_text("a\n1\n")
        store = AppStore(tmp_path / ".shipit" / "apps")
        app = store.create("peek", title="Peek", files={"app.py": self.READS})
        assert not run_app(app, {"path": "data.csv"}).value["found"]


class TestArtifactEvents:
    """The runtime reports files a tool declared — and only those."""

    def test_a_declared_path_becomes_an_artifact(self, tmp_path) -> None:
        from shipit_agent.runtime_core import _artifact_kind, _declared_paths

        page = tmp_path / "revenue.html"
        page.write_text("<h1>hi</h1>")
        found = _declared_paths({"path": str(page)})
        assert [p.name for p in found] == ["revenue.html"]
        assert _artifact_kind(page) == "Page"

    def test_a_path_that_does_not_exist_is_not_an_artifact(self, tmp_path) -> None:
        from shipit_agent.runtime_core import _declared_paths

        assert _declared_paths({"path": str(tmp_path / "nope.html")}) == []

    def test_lists_are_read_too(self, tmp_path) -> None:
        from shipit_agent.runtime_core import _declared_paths

        for name in ("a.csv", "b.csv"):
            (tmp_path / name).write_text("x\n")
        found = _declared_paths({"paths": [str(tmp_path / "a.csv"),
                                           str(tmp_path / "b.csv")]})
        assert len(found) == 2

    def test_free_text_is_never_scraped(self, tmp_path) -> None:
        """Guessing paths out of output would invent artifacts constantly."""
        from shipit_agent.runtime_core import _declared_paths

        real = tmp_path / "real.csv"
        real.write_text("x\n")
        assert _declared_paths({"output": f"wrote {real}"}) == []

    def test_kinds_are_named_for_people(self) -> None:
        from shipit_agent.runtime_core import _artifact_kind

        assert _artifact_kind("a.csv") == "Sheet"
        assert _artifact_kind("a.md") == "Doc"
        assert _artifact_kind("a.pptx") == "Deck"
        assert _artifact_kind("a.wat") == "File"


class TestUseAppDeclaresWhatItMade:
    """An app that writes a file must say so, or there is no card to draw."""

    def test_a_produced_file_is_declared(self, tools, tmp_path) -> None:
        tools["create_app"].run(ctx(), name="pager", title="Guest page",
                                blueprint="page")
        out = tools["use_app"].run(
            ctx(), app="pager",
            input={"rows": [{"name": "Dana"}], "output": "guests.html"},
        )
        assert out.metadata["ok"]
        assert out.metadata["path"].endswith("guests.html")
        assert out.metadata["title"] == "Guest page"

    def test_an_app_that_writes_nothing_declares_nothing(self, tools) -> None:
        tools["create_app"].run(ctx(), name="quiet", title="Quiet",
                                blueprint="report")
        out = tools["use_app"].run(ctx(), app="quiet", input={"rows": [{"a": 1}]})
        assert "path" not in out.metadata

    def test_a_path_that_was_never_written_is_not_declared(self) -> None:
        from shipit_agent.tools.apps.apps_tools import _produced_path

        assert _produced_path({"path": "/nowhere/nothing.html"}) is None
        assert _produced_path("not a dict") is None


class TestReadsAreNotArtifacts:
    """Reading a file does not produce one — the user already had it."""

    def test_a_read_declares_no_artifact(self, tmp_path) -> None:
        from shipit_agent.models import AgentEvent
        from shipit_agent.runtime_core import RuntimeCore

        data = tmp_path / "guests.csv"
        data.write_text("name\nDana\n")

        emitted: list[str] = []

        class Probe(RuntimeCore):
            # `event_type`, not `kind`: an artifact payload carries a `kind`
            # of its own, and naming the parameter that collides with it.
            def emit(self, state, event_type, message, **payload):
                emitted.append(event_type)

        class Result:
            metadata = {"path": str(data)}

        probe = Probe.__new__(Probe)   # no runtime, just the shared helper
        probe.note_artifacts(None, "read_file", Result())
        assert emitted == [], "read_file reports what it read, not what it made"

        probe.note_artifacts(None, "write_file", Result())
        assert emitted == ["artifact_created"]
        assert AgentEvent  # imported for the type it documents
