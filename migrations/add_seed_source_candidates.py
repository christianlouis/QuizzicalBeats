"""Persist external catalog candidates for review before any song import."""

import logging

from sqlalchemy import inspect

logger = logging.getLogger(__name__)


def run_migration():
    """Create the review-only candidate table and its indexes when absent."""
    try:
        from musicround import db
        from musicround.models import SeedSourceCandidate

        with db.engine.begin() as connection:
            inspector = inspect(connection)
            if 'seed_source_candidate' in inspector.get_table_names():
                return None
            SeedSourceCandidate.__table__.create(bind=connection)
        return True
    except Exception as exc:
        logger.error('Migration add_seed_source_candidates failed: %s', exc)
        return False
