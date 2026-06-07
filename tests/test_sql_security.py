"""Security regression tests for SQLTool (SEC-3 read-only bypass, SEC-7 timeout).

SEC-3: ``_is_read_only`` only scanned the first 500 chars, so a trailing
``; DELETE ...`` rode past a long leading SELECT. It now scans the entire
statement and rejects multiple statements.

SEC-7: ``timeout_seconds`` is applied best-effort per dialect; the docstring
is now honest about the limitation.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.sql import SQLTool
from shipit_agent.tools.sql.sql_tool import _is_read_only


class TestReadOnlyBypass:
    def test_trailing_delete_past_500_chars_is_rejected(self) -> None:
        sql = "SELECT 1" + " " * 600 + "; DELETE FROM users"
        assert _is_read_only(sql) is False

    def test_short_stacked_delete_rejected(self) -> None:
        assert _is_read_only("SELECT 1; DELETE FROM users") is False

    def test_stacked_drop_rejected(self) -> None:
        assert _is_read_only("SELECT * FROM t; DROP TABLE t") is False

    def test_two_selects_rejected_as_multi_statement(self) -> None:
        # Multiple statements are rejected even when both are reads.
        assert _is_read_only("SELECT 1; SELECT 2") is False

    def test_single_select_trailing_semicolon_ok(self) -> None:
        assert _is_read_only("SELECT 1;") is True

    def test_single_select_no_semicolon_ok(self) -> None:
        assert _is_read_only("SELECT * FROM users WHERE id = 1") is True

    def test_cte_still_ok(self) -> None:
        assert _is_read_only("WITH x AS (SELECT 1) SELECT * FROM x") is True

    def test_leading_semicolon_still_ok(self) -> None:
        assert _is_read_only(";SELECT 1") is True


class TestTimeoutDocstringHonest:
    def test_docstring_does_not_overclaim_universal_timeout(self) -> None:
        import shipit_agent.tools.sql.sql_tool as mod

        doc = mod.__doc__ or ""
        assert "best-effort" in doc.lower()

    def test_apply_statement_timeout_emits_for_postgres(self) -> None:
        sa = pytest.importorskip("sqlalchemy")  # noqa: F841
        from sqlalchemy import text as sa_text

        executed: list[str] = []

        class FakeDialect:
            name = "postgresql"

        class FakeConn:
            dialect = FakeDialect()

            def execute(self, stmt, *a, **k):
                executed.append(str(stmt))

        tool = SQLTool(timeout_seconds=7)
        tool._apply_statement_timeout(FakeConn(), sa_text)
        assert any("statement_timeout" in s for s in executed)
        assert any("7000" in s for s in executed)

    def test_apply_statement_timeout_noop_for_sqlite(self) -> None:
        pytest.importorskip("sqlalchemy")
        from sqlalchemy import text as sa_text

        executed: list[str] = []

        class FakeDialect:
            name = "sqlite"

        class FakeConn:
            dialect = FakeDialect()

            def execute(self, stmt, *a, **k):
                executed.append(str(stmt))

        tool = SQLTool(timeout_seconds=7)
        tool._apply_statement_timeout(FakeConn(), sa_text)
        assert executed == []
