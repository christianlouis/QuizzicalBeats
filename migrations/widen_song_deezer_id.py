"""Widen song.deezer_id for large Deezer catalog ids."""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app
from sqlalchemy import inspect, text

from musicround import db


logger = logging.getLogger(__name__)


def run_migration():
    """Make song.deezer_id a BIGINT on PostgreSQL.

    Deezer track ids can exceed PostgreSQL INTEGER range. SQLite stores dynamic
    integer values already, so no type rewrite is needed there.
    """
    engine = db.engine
    if engine.dialect.name == "sqlite":
        logger.info("SQLite does not require widening song.deezer_id")
        return None

    inspector = inspect(engine)
    if not inspector.has_table("song"):
        logger.info("song table does not exist yet")
        return None

    columns = {column["name"]: column for column in inspector.get_columns("song")}
    column = columns.get("deezer_id")
    if not column:
        logger.info("song.deezer_id does not exist yet")
        return None

    if isinstance(column["type"], sa.BigInteger) or str(column["type"]).upper() == "BIGINT":
        logger.info("song.deezer_id is already BIGINT")
        return None

    if engine.dialect.name != "postgresql":
        logger.warning(
            "Unsupported database dialect for widening song.deezer_id: %s",
            engine.dialect.name,
        )
        return False

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE song ALTER COLUMN deezer_id TYPE BIGINT"))

    current_app.logger.info("Widened song.deezer_id to BIGINT")
    return True
