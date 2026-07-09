"""Widen song.source for legacy import source labels."""

from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import inspect, text

from musicround import db


logger = logging.getLogger(__name__)


def run_migration():
    """Allow longer source labels imported from curated catalogs."""
    engine = db.engine
    if engine.dialect.name == "sqlite":
        logger.info("SQLite does not require widening song.source")
        return None

    inspector = inspect(engine)
    if not inspector.has_table("song"):
        logger.info("song table does not exist yet")
        return None

    columns = {column["name"]: column for column in inspector.get_columns("song")}
    column = columns.get("source")
    if not column:
        logger.info("song.source does not exist yet")
        return None

    current_length = getattr(column["type"], "length", None)
    if current_length is not None and current_length >= 50:
        logger.info("song.source is already wide enough")
        return None

    if engine.dialect.name != "postgresql":
        logger.warning(
            "Unsupported database dialect for widening song.source: %s",
            engine.dialect.name,
        )
        return False

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE song ALTER COLUMN source TYPE VARCHAR(50)"))

    current_app.logger.info("Widened song.source to VARCHAR(50)")
    return True
