"""SQLTool — a single SQLAlchemy-backed tool covering every dialect.

The tool is *lazy* with respect to SQLAlchemy: the library is only
imported inside :meth:`run`, so constructing a :class:`SQLTool` does
not require SQLAlchemy to be installed. Callers pass a SQLAlchemy URL
(``postgresql://...``, ``bigquery://project``, ``sqlite:///:memory:``,
etc.) or a pre-built ``Engine`` and the tool handles the rest.

Safety posture:

* ``allow_writes=False`` (the default) rejects anything that isn't a
  pure ``SELECT`` or ``WITH ... SELECT`` CTE.
* ``max_rows`` caps the row count returned on any ``query``.
* ``timeout_seconds`` is applied on a *best-effort, dialect-dependent*
  basis: PostgreSQL gets ``SET LOCAL statement_timeout`` and MySQL/MariaDB
  get ``max_execution_time`` per statement. SQLAlchemy exposes no portable
  cross-dialect statement timeout, so dialects without a supported mechanism
  (e.g. SQLite) are *not* time-bounded — do not rely on it there.
* Exceptions are caught and surfaced as structured metadata — the tool
  never raises from :meth:`run`.
"""

from __future__ import annotations

import base64
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import SQL_PROMPT

_ACTIONS = ("query", "execute", "list_tables", "describe_table", "schema_summary")

# Keywords that mean "not a pure read". Matched case-insensitively as
# whole words at the head of the statement (after stripping comments
# and leading whitespace).
_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
    "MERGE",
)

_WRITE_PATTERN = re.compile(
    r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Strip /* ... */ block comments and -- line comments.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _strip_comments(sql: str) -> str:
    without_block = _BLOCK_COMMENT.sub(" ", sql)
    return _LINE_COMMENT.sub(" ", without_block)


def _is_read_only(sql: str) -> bool:
    """Return True iff ``sql`` is a single pure SELECT (or WITH...SELECT CTE).

    The check scans the *entire* cleaned statement (after comments and
    leading whitespace/semicolons are removed) and rejects it if any
    mutation keyword appears anywhere, or if it contains more than one
    statement (a ``;`` followed by additional non-empty SQL). Scanning the
    whole string — rather than just the head — closes the bypass where a
    trailing ``; DELETE ...`` rides past a long leading SELECT. The CTE form
    is accepted because ``WITH ... SELECT`` is still a read.

    A semicolon inside a string literal will be (conservatively) treated as a
    statement separator; this fails *safe* — it rejects a legitimate query
    rather than admitting a write.
    """
    if not sql or not sql.strip():
        return False

    cleaned = _strip_comments(sql).strip().lstrip(";").strip()
    if not cleaned:
        return False

    # Reject multiple statements: drop a single trailing ``;`` then split.
    # ``SELECT 1;`` → 1 segment (OK); ``SELECT 1; DELETE ...`` → 2 (reject).
    trimmed = cleaned.rstrip().rstrip(";").rstrip()
    segments = [seg for seg in trimmed.split(";") if seg.strip()]
    if len(segments) > 1:
        return False

    # If any write keyword appears as a whole word anywhere, reject.
    if _WRITE_PATTERN.search(cleaned):
        return False

    lowered = cleaned.lower()
    if lowered.startswith("select") or lowered.startswith("with") or lowered.startswith("("):
        return True
    # ``VALUES ...`` and ``TABLE foo`` are technically reads in some
    # dialects but we keep the whitelist tight — explicit SELECT/WITH/(
    # only.
    return False


def _jsonify(value: Any) -> Any:
    """Convert SQLAlchemy-returned scalars into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "base64:" + base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    # Fall back to string for exotic types (UUID, Enum, etc).
    return str(value)


def _render_markdown_table(rows: list[dict[str, Any]], limit: int = 10) -> str:
    if not rows:
        return "(no rows)"
    columns = list(rows[0].keys())
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines: list[str] = []
    for row in rows[:limit]:
        cells = [str(_jsonify(row.get(c, ""))) for c in columns]
        body_lines.append("| " + " | ".join(cells) + " |")
    tail = ""
    if len(rows) > limit:
        tail = f"\n... ({len(rows) - limit} more rows)"
    return "\n".join([head, sep, *body_lines]) + tail


class SQLTool:
    """Single SQL tool for every SQLAlchemy dialect.

    Construction is cheap and never imports SQLAlchemy. The real work —
    engine creation, schema reflection, query execution — happens on
    the first :meth:`run` call.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        engine: Any = None,
        allow_writes: bool = False,
        max_rows: int = 500,
        timeout_seconds: int = 30,
        name: str = "sql",
        description: str = (
            "Query a SQL database. Reads by default; set allow_writes=True "
            "to enable mutations."
        ),
        prompt: str | None = None,
    ) -> None:
        self.url = url
        self.engine = engine
        self.allow_writes = bool(allow_writes)
        self.max_rows = int(max_rows)
        self.timeout_seconds = int(timeout_seconds)
        self.name = name
        self.description = description
        self.prompt = prompt or SQL_PROMPT
        self.prompt_instructions = (
            "Use when the user's question is answered by rows in a relational "
            "database. Explore with list_tables / describe_table first if the "
            "schema is unknown."
        )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": list(_ACTIONS),
                            "description": (
                                "What to do: query (SELECT), execute (mutate; "
                                "requires allow_writes=True), list_tables, "
                                "describe_table, schema_summary."
                            ),
                        },
                        "sql": {
                            "type": "string",
                            "description": (
                                "SQL statement. Required for action=query and "
                                "action=execute. Prefer :named parameters over "
                                "concatenation."
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": "Named parameters substituted into :name placeholders.",
                        },
                        "table": {
                            "type": "string",
                            "description": "Table name (required for action=describe_table).",
                        },
                        "schema": {
                            "type": "string",
                            "description": "Optional schema/database qualifier for describe_table.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Cap for action=schema_summary (default 50).",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        # Late import so module import doesn't require SQLAlchemy.
        try:
            import sqlalchemy as sa  # noqa: F401
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy import text as sa_text
            from sqlalchemy.exc import SQLAlchemyError
        except ImportError:
            return ToolOutput(
                text=(
                    "SQL tool requires SQLAlchemy. Install it with:\n"
                    "    pip install 'shipit-agent[sql]'\n"
                    "or directly: pip install 'sqlalchemy>=2.0'."
                ),
                metadata={
                    "error": "sqlalchemy_missing",
                    "install_hint": "pip install 'shipit-agent[sql]'",
                },
            )

        action = str(kwargs.get("action") or "query").strip().lower()
        if action not in _ACTIONS:
            return ToolOutput(
                text=f"Unknown action: {action}. Expected one of {list(_ACTIONS)}.",
                metadata={"error": "bad_action", "action": action},
            )

        engine_or_err = self._resolve_engine(context)
        if isinstance(engine_or_err, ToolOutput):
            return engine_or_err
        engine = engine_or_err

        try:
            if action == "query":
                return self._do_query(engine, kwargs, sa_text, SQLAlchemyError)
            if action == "execute":
                return self._do_execute(engine, kwargs, sa_text, SQLAlchemyError)
            if action == "list_tables":
                return self._do_list_tables(engine, sa_inspect, SQLAlchemyError)
            if action == "describe_table":
                return self._do_describe_table(
                    engine, kwargs, sa_inspect, SQLAlchemyError
                )
            if action == "schema_summary":
                return self._do_schema_summary(
                    engine, kwargs, sa_inspect, SQLAlchemyError
                )
        except SQLAlchemyError as exc:  # pragma: no cover — defensive
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={"error": "sql_error", "message": str(exc)},
            )

        # Should be unreachable — every action branch returns above.
        return ToolOutput(  # pragma: no cover
            text="Unhandled action.",
            metadata={"error": "unhandled", "action": action},
        )

    # ------------------------------------------------------------------
    # Connection resolution
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Statement timeout (best-effort, dialect-dependent)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
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

    def _do_list_tables(
        self,
        engine: Any,
        sa_inspect: Any,
        SQLAlchemyError: type[Exception],
    ) -> ToolOutput:
        try:
            inspector = sa_inspect(engine)
            tables = list(inspector.get_table_names())
        except SQLAlchemyError as exc:
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={"error": "sql_error", "message": str(exc)},
            )
        text = "\n".join(f"- {t}" for t in tables) if tables else "(no tables)"
        return ToolOutput(
            text=text,
            metadata={
                "action": "list_tables",
                "tables": tables,
                "count": len(tables),
            },
        )

    def _do_describe_table(
        self,
        engine: Any,
        kwargs: dict[str, Any],
        sa_inspect: Any,
        SQLAlchemyError: type[Exception],
    ) -> ToolOutput:
        table = str(kwargs.get("table") or "").strip()
        if not table:
            return ToolOutput(
                text="Missing table.",
                metadata={"error": "missing_table"},
            )
        schema = kwargs.get("schema") or None
        try:
            inspector = sa_inspect(engine)
            columns = inspector.get_columns(table, schema=schema)
        except SQLAlchemyError as exc:
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={
                    "error": "sql_error",
                    "message": str(exc),
                    "table": table,
                },
            )

        serialised: list[dict[str, Any]] = []
        for col in columns:
            serialised.append(
                {
                    "name": col.get("name"),
                    "type": str(col.get("type")),
                    "nullable": bool(col.get("nullable", True)),
                    "default": _jsonify(col.get("default")),
                    "primary_key": bool(col.get("primary_key", False)),
                }
            )

        lines = [f"Table: {table}"]
        for c in serialised:
            nn = "NULL" if c["nullable"] else "NOT NULL"
            pk = " PK" if c["primary_key"] else ""
            lines.append(f"- {c['name']}: {c['type']} {nn}{pk}")
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "action": "describe_table",
                "table": table,
                "schema": schema,
                "columns": serialised,
            },
        )

    def _do_schema_summary(
        self,
        engine: Any,
        kwargs: dict[str, Any],
        sa_inspect: Any,
        SQLAlchemyError: type[Exception],
    ) -> ToolOutput:
        limit = int(kwargs.get("limit") or 50)
        try:
            inspector = sa_inspect(engine)
            tables = list(inspector.get_table_names())[:limit]
            summary: list[dict[str, Any]] = []
            for t in tables:
                try:
                    cols = inspector.get_columns(t)
                except SQLAlchemyError:
                    cols = []
                summary.append({"table": t, "column_count": len(cols)})
        except SQLAlchemyError as exc:
            return ToolOutput(
                text=f"SQL error: {exc}",
                metadata={"error": "sql_error", "message": str(exc)},
            )

        lines = [f"- {s['table']} ({s['column_count']} cols)" for s in summary]
        text = "\n".join(lines) if lines else "(no tables)"
        return ToolOutput(
            text=text,
            metadata={
                "action": "schema_summary",
                "tables": summary,
                "count": len(summary),
                "limit": limit,
            },
        )


__all__ = ["SQLTool", "_is_read_only", "_jsonify"]
