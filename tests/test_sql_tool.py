"""Tests for SQLTool — the single SQLAlchemy-backed tool.

Unit tests for the pure-Python helpers (``_is_read_only``, ``_jsonify``)
always run; the integration tests require SQLAlchemy and are skipped
with a clear message when it isn't available.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.sql import SQLTool
from shipit_agent.tools.sql.sql_tool import _is_read_only, _jsonify

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")


# ─────────────────────── unit: _is_read_only ───────────────────────


class TestIsReadOnly:
    def test_plain_select_is_read_only(self) -> None:
        assert _is_read_only("SELECT 1") is True
        assert _is_read_only("select * from users") is True

    def test_leading_whitespace_ok(self) -> None:
        assert _is_read_only("   \n\t SELECT 1  ") is True

    def test_leading_semicolon_ok(self) -> None:
        assert _is_read_only(";SELECT 1") is True

    def test_line_comments_are_stripped(self) -> None:
        assert _is_read_only("-- a comment\nSELECT 1") is True

    def test_block_comments_are_stripped(self) -> None:
        assert _is_read_only("/* hi */ SELECT 1") is True

    def test_cte_with_select_is_read_only(self) -> None:
        assert (
            _is_read_only("WITH x AS (SELECT 1 AS n) SELECT * FROM x") is True
        )
        assert _is_read_only("with x as (select 1) select * from x") is True

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET a = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "ALTER TABLE t ADD COLUMN c INT",
            "CREATE TABLE t (id INT)",
            "TRUNCATE TABLE t",
            "REPLACE INTO t VALUES (1)",
            "GRANT SELECT ON t TO u",
            "REVOKE SELECT ON t FROM u",
            "MERGE INTO t USING s ON a=b WHEN MATCHED THEN UPDATE SET x=1",
        ],
    )
    def test_mutation_keywords_rejected(self, sql: str) -> None:
        assert _is_read_only(sql) is False

    @pytest.mark.parametrize(
        "sql",
        [
            "insert into t values (1)",
            "Update t set a=1",
            "dRoP table t",
        ],
    )
    def test_case_insensitive(self, sql: str) -> None:
        assert _is_read_only(sql) is False

    def test_empty_is_not_read_only(self) -> None:
        assert _is_read_only("") is False
        assert _is_read_only("   \n\t ") is False

    def test_random_keyword_that_is_not_select_is_rejected(self) -> None:
        # VALUES / TABLE / SHOW aren't in the allow-list — conservative.
        assert _is_read_only("VALUES (1, 2)") is False


# ─────────────────────── unit: _jsonify ───────────────────────


class TestJsonify:
    def test_passthrough_primitives(self) -> None:
        assert _jsonify(None) is None
        assert _jsonify(1) == 1
        assert _jsonify(1.5) == 1.5
        assert _jsonify(True) is True
        assert _jsonify("x") == "x"

    def test_date_becomes_isoformat(self) -> None:
        assert _jsonify(date(2026, 4, 24)) == "2026-04-24"

    def test_datetime_becomes_isoformat(self) -> None:
        assert _jsonify(datetime(2026, 4, 24, 12, 30)) == "2026-04-24T12:30:00"

    def test_time_becomes_isoformat(self) -> None:
        assert _jsonify(time(8, 15)) == "08:15:00"

    def test_decimal_becomes_float(self) -> None:
        out = _jsonify(Decimal("1.25"))
        assert isinstance(out, float) and out == 1.25

    def test_bytes_becomes_base64_prefixed(self) -> None:
        encoded = _jsonify(b"hi\x00there")
        assert encoded.startswith("base64:")
        assert base64.b64decode(encoded[len("base64:") :]) == b"hi\x00there"

    def test_nested_collections(self) -> None:
        out = _jsonify([Decimal("1"), {"d": date(2026, 1, 1)}, (b"a",)])
        assert out == [1.0, {"d": "2026-01-01"}, ["base64:YQ=="]]


# ─────────────────────── unit: tool shape ───────────────────────


class TestToolShape:
    def test_name_default(self) -> None:
        assert SQLTool().name == "sql"

    def test_description_default(self) -> None:
        tool = SQLTool()
        assert "SQL" in tool.description or "database" in tool.description.lower()

    def test_schema_has_action_enum_with_all_actions(self) -> None:
        schema = SQLTool().schema()
        action_enum = schema["function"]["parameters"]["properties"]["action"]["enum"]
        assert set(action_enum) == {
            "query",
            "execute",
            "list_tables",
            "describe_table",
            "schema_summary",
        }
        assert schema["function"]["parameters"]["required"] == ["action"]


# ─────────────────────── missing-connection path ───────────────────────


class TestMissingConnection:
    def test_no_url_no_engine_returns_friendly_error(self) -> None:
        tool = SQLTool()
        out = tool.run(ToolContext(prompt="x"), action="query", sql="SELECT 1")
        assert out.metadata.get("error") == "no_connection"


# ─────────────────────── integration: in-memory sqlite ───────────────────────


@pytest.fixture()
def engine():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine, text

    # A single shared in-memory DB needs StaticPool so multiple
    # connections see the same tables.
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "score REAL"
                ")"
            )
        )
        for i, (name, score) in enumerate(
            [("alice", 1.5), ("bob", 2.5), ("carol", 3.5), ("dave", 4.5)],
            start=1,
        ):
            conn.execute(
                text("INSERT INTO users(id, name, score) VALUES(:i,:n,:s)"),
                {"i": i, "n": name, "s": score},
            )
    return eng


class TestQueryIntegration:
    def test_query_returns_rows_and_markdown_text(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(
            ToolContext(prompt="x"),
            action="query",
            sql="SELECT id, name, score FROM users ORDER BY id",
        )
        assert out.metadata.get("error") is None
        assert out.metadata["action"] == "query"
        rows = out.metadata["rows"]
        assert len(rows) == 4
        assert rows[0] == {"id": 1, "name": "alice", "score": 1.5}
        # Markdown table with header row + separator row.
        assert "| id | name | score |" in out.text
        assert "| --- | --- | --- |" in out.text
        assert "alice" in out.text

    def test_row_cap_marks_truncated(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine, max_rows=3)
        out = tool.run(
            ToolContext(prompt="x"),
            action="query",
            sql="SELECT * FROM users",
        )
        assert out.metadata.get("truncated") is True
        assert out.metadata["row_count"] == 3
        assert out.metadata["total_before_truncation"] == 4

    def test_query_accepts_named_params(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(
            ToolContext(prompt="x"),
            action="query",
            sql="SELECT name FROM users WHERE id = :uid",
            params={"uid": 2},
        )
        assert out.metadata["rows"] == [{"name": "bob"}]


class TestSchemaActions:
    def test_list_tables(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(ToolContext(prompt="x"), action="list_tables")
        assert "users" in out.metadata["tables"]
        assert "- users" in out.text

    def test_describe_table(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(
            ToolContext(prompt="x"),
            action="describe_table",
            table="users",
        )
        cols = {c["name"]: c for c in out.metadata["columns"]}
        assert set(cols) == {"id", "name", "score"}
        assert cols["name"]["nullable"] is False
        # Type string should mention INTEGER / TEXT / REAL somewhere.
        assert "INTEGER" in cols["id"]["type"].upper()
        assert "TEXT" in cols["name"]["type"].upper()

    def test_describe_missing_table_argument(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(ToolContext(prompt="x"), action="describe_table")
        assert out.metadata["error"] == "missing_table"

    def test_schema_summary(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(ToolContext(prompt="x"), action="schema_summary")
        tables = out.metadata["tables"]
        assert any(t["table"] == "users" and t["column_count"] == 3 for t in tables)


class TestWriteGuard:
    def test_query_rejects_write_when_allow_writes_false(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine, allow_writes=False)
        out = tool.run(
            ToolContext(prompt="x"),
            action="query",
            sql="UPDATE users SET name='x' WHERE id=1",
        )
        assert out.metadata["error"] == "write_not_allowed"

    def test_execute_rejected_when_allow_writes_false(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine, allow_writes=False)
        out = tool.run(
            ToolContext(prompt="x"),
            action="execute",
            sql="INSERT INTO users(id,name) VALUES(99,'eve')",
        )
        assert out.metadata["error"] == "writes_disabled"

    def test_execute_accepted_when_allow_writes_true(self, engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        tool = SQLTool(engine=engine, allow_writes=True)
        out = tool.run(
            ToolContext(prompt="x"),
            action="execute",
            sql="INSERT INTO users(id,name,score) VALUES(:i,:n,:s)",
            params={"i": 99, "n": "eve", "s": 9.9},
        )
        assert out.metadata.get("error") is None
        assert out.metadata["action"] == "execute"
        # Verify the row actually landed.
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT name, score FROM users WHERE id=99")
            ).one()
        assert row.name == "eve"
        assert row.score == 9.9


class TestErrorSurfacing:
    def test_bad_sql_returns_structured_error(self, engine) -> None:  # type: ignore[no-untyped-def]
        tool = SQLTool(engine=engine)
        out = tool.run(
            ToolContext(prompt="x"),
            action="query",
            sql="SELECT FROM nothing",
        )
        assert out.metadata["error"] == "sql_error"
        assert "message" in out.metadata
        assert out.metadata["sql"].startswith("SELECT")


class TestContextStateURL:
    def test_url_from_context_state_is_used(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        # Use a file-based sqlite DB so connections reopen cleanly.
        db = tmp_path / "ctx.sqlite"
        from sqlalchemy import create_engine, text

        bootstrap = create_engine(f"sqlite:///{db}")
        with bootstrap.begin() as conn:
            conn.execute(text("CREATE TABLE t (x INTEGER)"))
            conn.execute(text("INSERT INTO t(x) VALUES (42)"))
        bootstrap.dispose()

        tool = SQLTool()  # no url, no engine
        ctx = ToolContext(prompt="x", state={"sql_url": f"sqlite:///{db}"})
        out = tool.run(ctx, action="query", sql="SELECT x FROM t")
        assert out.metadata["rows"] == [{"x": 42}]


# ─────────────────────── missing-SQLAlchemy path ───────────────────────


class TestMissingSQLAlchemy:
    def test_import_failure_is_surfaced(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """If SQLAlchemy is absent at run() time, the tool returns a
        friendly ``sqlalchemy_missing`` error instead of raising."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "sqlalchemy" or name.startswith("sqlalchemy."):
                raise ImportError("no sqlalchemy in this env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        tool = SQLTool(url="sqlite:///:memory:")
        out = tool.run(ToolContext(prompt="x"), action="query", sql="SELECT 1")
        assert out.metadata["error"] == "sqlalchemy_missing"
        assert "install_hint" in out.metadata
