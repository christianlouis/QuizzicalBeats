"""Credential-safe helpers for moving the legacy SQLite DB to managed SQL."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from musicround import db
from musicround.helpers.database_config import database_backend, redact_database_uri


class DatabaseMigrationError(RuntimeError):
    """Raised when a migration precondition fails."""


@dataclass(frozen=True)
class TableCopyResult:
    table: str
    source_rows: int
    target_rows_before: int
    target_rows_after: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "source_rows": self.source_rows,
            "target_rows_before": self.target_rows_before,
            "target_rows_after": self.target_rows_after,
        }


def migrate_sqlite_to_configured_database(
    source_path: str,
    target_engine: Engine,
    *,
    execute: bool = False,
    replace_target: bool = False,
    allow_sqlite_target: bool = False,
) -> dict[str, Any]:
    """Copy rows from a SQLite file into the already configured target engine.

    The default mode is a dry run. Execution is intentionally opt-in because
    this helper is meant for production cutover work.
    """
    source_path = os.path.abspath(source_path)
    if not os.path.exists(source_path):
        raise DatabaseMigrationError("Source SQLite database file does not exist.")
    if not os.path.isfile(source_path):
        raise DatabaseMigrationError("Source SQLite database path is not a file.")

    target_uri = str(target_engine.url)
    if database_backend(target_uri) == "sqlite" and not allow_sqlite_target:
        raise DatabaseMigrationError(
            "Refusing to migrate into a SQLite target. Configure managed SQL or "
            "pass --allow-sqlite-target for local tests only."
        )

    source_engine = create_engine(f"sqlite:///{source_path}")
    db.create_all()

    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            source_inspector = inspect(source)
            results = []
            for table in db.metadata.sorted_tables:
                source_rows = _count_table(source, table.name, source_inspector)
                target_rows_before = _count_table(target, table.name)
                results.append(
                    TableCopyResult(
                        table=table.name,
                        source_rows=source_rows,
                        target_rows_before=target_rows_before,
                    )
                )

            target_nonempty = any(result.target_rows_before for result in results)
            if target_nonempty and execute and not replace_target:
                raise DatabaseMigrationError(
                    "Target database already contains rows. Re-run with "
                    "--replace-target after taking a backup, or use a fresh "
                    "managed database."
                )

            copied_results = results
            if execute:
                if replace_target:
                    _delete_target_rows(target)
                copied_results = _copy_tables(source, target, source_inspector)
                _reset_postgres_sequences(target_engine, target)

            return {
                "mode": "execute" if execute else "dry-run",
                "source": "sqlite:///[source-file]",
                "target": redact_database_uri(target_uri),
                "target_nonempty": target_nonempty,
                "tables": [result.to_dict() for result in copied_results],
                "total_source_rows": sum(result.source_rows for result in results),
                "total_target_rows_before": sum(
                    result.target_rows_before for result in results
                ),
                "total_target_rows_after": (
                    sum(result.target_rows_after or 0 for result in copied_results)
                    if execute
                    else None
                ),
            }
    except SQLAlchemyError as exc:
        raise DatabaseMigrationError("Database migration failed.") from exc
    finally:
        source_engine.dispose()


def _count_table(connection, table_name: str, inspector=None) -> int:
    if inspector is not None and not inspector.has_table(table_name):
        return 0
    result = connection.execute(text(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}"))
    return int(result.scalar() or 0)


def _copy_tables(source, target, source_inspector) -> list[TableCopyResult]:
    results: list[TableCopyResult] = []
    for table in db.metadata.sorted_tables:
        if not source_inspector.has_table(table.name):
            source_rows = 0
        else:
            source_columns = {column["name"] for column in source_inspector.get_columns(table.name)}
            selected_columns = [
                column for column in table.columns if column.name in source_columns
            ]
            rows = [
                dict(row._mapping)
                for row in source.execute(select(*selected_columns)).fetchall()
            ]
            source_rows = len(rows)
            if rows:
                target.execute(table.insert(), rows)
        target_rows_after = _count_table(target, table.name)
        results.append(
            TableCopyResult(
                table=table.name,
                source_rows=source_rows,
                target_rows_before=0,
                target_rows_after=target_rows_after,
            )
        )
    return results


def _delete_target_rows(target) -> None:
    for table in reversed(db.metadata.sorted_tables):
        target.execute(table.delete())


def _reset_postgres_sequences(target_engine: Engine, target) -> None:
    if database_backend(str(target_engine.url)) != "postgresql":
        return

    preparer = target_engine.dialect.identifier_preparer
    for table in db.metadata.sorted_tables:
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            continue
        primary_key = primary_keys[0]
        try:
            python_type = primary_key.type.python_type
        except NotImplementedError:
            continue
        if python_type is not int:
            continue
        quoted_table = preparer.quote(table.name)
        quoted_column = preparer.quote(primary_key.name)
        target.execute(
            text(
                "SELECT setval("
                "pg_get_serial_sequence(:table_name, :column_name), "
                f"COALESCE((SELECT MAX({quoted_column}) FROM {quoted_table}), 0) + 1, "
                "false)"
            ),
            {"table_name": table.name, "column_name": primary_key.name},
        )


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
