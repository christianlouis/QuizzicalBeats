"""Add provider identifiers needed by trusted catalog source adapters."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def run_migration():
    """Add provider IDs and source evidence to existing candidate tables."""
    try:
        from musicround import db

        with db.engine.begin() as connection:
            inspector = inspect(connection)
            if 'seed_source_candidate' not in inspector.get_table_names():
                return None
            columns = {column['name'] for column in inspector.get_columns('seed_source_candidate')}
            changed = False
            if 'deezer_id' not in columns:
                connection.execute(text(
                    'ALTER TABLE seed_source_candidate ADD COLUMN deezer_id VARCHAR(64)'
                ))
                changed = True
            if 'recording_mbid' not in columns:
                connection.execute(text(
                    'ALTER TABLE seed_source_candidate ADD COLUMN recording_mbid VARCHAR(36)'
                ))
                changed = True
            if 'source_score' not in columns:
                connection.execute(text(
                    'ALTER TABLE seed_source_candidate ADD COLUMN source_score BIGINT'
                ))
                changed = True
        return True if changed else None
    except Exception as exc:
        logger.error('Migration extend_seed_source_candidate_identifiers failed: %s', exc)
        return False
