"""SQL schema introspection: tables, columns and a schema summary."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput

from .statements import (
    _jsonify,
)


class _IntrospectionActions:
    """SQL schema introspection: tables, columns and a schema summary."""

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
