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

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .introspection import _IntrospectionActions
from .prompt import SQL_PROMPT
from .queries import _QueryActions
from .statements import _is_read_only as _is_read_only
from .statements import _jsonify as _jsonify

_ACTIONS = ("query", "execute", "list_tables", "describe_table", "schema_summary")

# Keywords that mean "not a pure read". Matched case-insensitively as
# whole words at the head of the statement (after stripping comments
# and leading whitespace).


# Strip /* ... */ block comments and -- line comments.


class SQLTool(_QueryActions, _IntrospectionActions):
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
    # Statement timeout (best-effort, dialect-dependent)

    # ------------------------------------------------------------------
    # Actions


__all__ = ["SQLTool", "_is_read_only", "_jsonify"]
