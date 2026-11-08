"""SQL engine setup, queries and statements."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .statements import (
    _is_read_only,
    _jsonify,
    _render_markdown_table,
)


class _QueryActions:
    """SQL engine setup, queries and statements."""

    def _resolve_engine(self, context: ToolContext) -> Any:
        if self.engine is not None:
            return self.engine
        url = self.url or context.state.get("sql_url")
        if not url:
            return ToolOutput(
                text=(
                    "No SQL connection configured. Pass url= or engine= to "
                    "SQLTool(), or set context.state['sql_url']."
                ),
                metadata={"error": "no_connection"},
            )
        from sqlalchemy import create_engine

        try:
            engine = create_engine(url)
        except Exception as exc:  # noqa: BLE001
            return ToolOutput(
                text=f"Failed to build engine from url: {exc}",
                metadata={"error": "engine_error", "message": str(exc)},
            )
        # Cache so repeated calls on the same tool reuse the engine.
        self.engine = engine
        return engine

    def _apply_statement_timeout(self, conn: Any, sa_text: Any) -> None:
        """Apply a per-statement timeout for dialects that support one.

        SQLAlchemy has no portable cross-dialect statement timeout, so we
        emit the appropriate session/transaction-scoped setting for the
        dialects that have one and silently no-op everywhere else. Failures
        to set the timeout are swallowed — a missing timeout must never break
        an otherwise-valid query.
        """
        if self.timeout_seconds is None or self.timeout_seconds <= 0:
            return
        dialect = getattr(getattr(conn, "dialect", None), "name", "") or ""
        dialect = dialect.lower()
        ms = int(self.timeout_seconds * 1000)
        try:
            if dialect in ("postgresql", "postgres"):
                conn.execute(sa_text(f"SET LOCAL statement_timeout = {ms}"))
            elif dialect in ("mysql", "mariadb"):
                conn.execute(sa_text(f"SET SESSION max_execution_time = {ms}"))
            # Other dialects (sqlite, mssql, bigquery, ...) have no portable
            # per-statement timeout we can set here; documented as a limitation.
        except Exception:  # noqa: BLE001 — best-effort; never block the query
            pass

    def _do_query(
        self,
        engine: Any,
        kwargs: dict[str, Any],
        sa_text: Any,
        SQLAlchemyError: type[Exception],
    ) -> ToolOutput:
        sql = str(kwargs.get("sql") or "").strip()
        if not sql:
            return ToolOutput(
                text="Missing sql.",
                metadata={"error": "missing_sql"},
            )
        if not self.allow_writes and not _is_read_only(sql):
            return ToolOutput(
                text=(
                    "Write/DDL statements are not allowed on this tool "
                    "(allow_writes=False). Use action=execute on a tool "
                    "constructed with allow_writes=True."
                ),
                metadata={
                    "error": "write_not_allowed",
                    "sql": sql[:200],
                },
            )
        params = kwargs.get("params") or {}
        try:
            with engine.connect() as conn:
                self._apply_statement_timeout(conn, sa_text)
                result = conn.execute(sa_text(sql), params)
                mappings = result.mappings().all()
        except SQLAlchemyError as exc:
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={
                    "error": "sql_error",
                    "message": str(exc),
                    "sql": sql[:200],
                },
            )

        rows: list[dict[str, Any]] = [
            {str(k): _jsonify(v) for k, v in m.items()} for m in mappings
        ]
        truncated = False
        total = len(rows)
        if len(rows) > self.max_rows:
            rows = rows[: self.max_rows]
            truncated = True

        text = _render_markdown_table(rows, limit=10)
        meta: dict[str, Any] = {
            "action": "query",
            "row_count": len(rows),
            "total_before_truncation": total,
            "rows": rows,
            "sql": sql[:200],
        }
        if truncated:
            meta["truncated"] = True
        return ToolOutput(text=text, metadata=meta)

    def _do_execute(
        self,
        engine: Any,
        kwargs: dict[str, Any],
        sa_text: Any,
        SQLAlchemyError: type[Exception],
    ) -> ToolOutput:
        if not self.allow_writes:
            return ToolOutput(
                text=(
                    "execute is disabled on this tool (allow_writes=False). "
                    "Re-construct SQLTool with allow_writes=True to enable "
                    "mutations."
                ),
                metadata={"error": "writes_disabled"},
            )
        sql = str(kwargs.get("sql") or "").strip()
        if not sql:
            return ToolOutput(
                text="Missing sql.",
                metadata={"error": "missing_sql"},
            )
        params = kwargs.get("params") or {}
        try:
            with engine.begin() as conn:
                self._apply_statement_timeout(conn, sa_text)
                result = conn.execute(sa_text(sql), params)
                rowcount = getattr(result, "rowcount", -1)
        except SQLAlchemyError as exc:
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={
                    "error": "sql_error",
                    "message": str(exc),
                    "sql": sql[:200],
                },
            )
        return ToolOutput(
            text=f"OK. rowcount={rowcount}",
            metadata={
                "action": "execute",
                "rowcount": rowcount,
                "sql": sql[:200],
            },
        )
