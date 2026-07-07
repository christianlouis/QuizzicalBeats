"""Add round ownership, sharing, and reviewable audio scripts."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _quote(identifier, preparer):
    return preparer.quote(identifier)


def _columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _table_exists(inspector, table_name):
    return table_name in set(inspector.get_table_names())


def _index_exists(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _create_index(conn, inspector, table_name, index_name, columns):
    if _index_exists(inspector, table_name, index_name):
        return False
    preparer = conn.dialect.identifier_preparer
    quoted_table = _quote(table_name, preparer)
    quoted_index = _quote(index_name, preparer)
    quoted_columns = ", ".join(_quote(column, preparer) for column in columns)
    conn.execute(text(f"CREATE INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"))
    return True


def run_migration():
    """Backfill collaboration and script-review schema on existing databases."""
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        if "round" not in existing_tables:
            logger.info("Skipping round collaboration migration because round table is missing")
            return None

        changes_made = False
        with db.engine.connect() as conn:
            preparer = conn.dialect.identifier_preparer
            round_table = _quote("round", preparer)
            round_columns = _columns(inspector, "round")
            if "user_id" not in round_columns:
                conn.execute(text(f"ALTER TABLE {round_table} ADD COLUMN user_id INTEGER"))
                changes_made = True
            if "visibility" not in round_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {round_table} "
                        "ADD COLUMN visibility VARCHAR(20) DEFAULT 'private' NOT NULL"
                    )
                )
                changes_made = True

            if not _table_exists(inspector, "round_share"):
                conn.execute(
                    text(
                        """
                        CREATE TABLE round_share (
                            id INTEGER PRIMARY KEY,
                            round_id INTEGER NOT NULL,
                            user_id INTEGER NOT NULL,
                            role VARCHAR(20) NOT NULL DEFAULT 'viewer',
                            created_at DATETIME,
                            UNIQUE(round_id, user_id)
                        )
                        """
                    )
                )
                changes_made = True

            if not _table_exists(inspector, "round_audio_script"):
                conn.execute(
                    text(
                        """
                        CREATE TABLE round_audio_script (
                            id INTEGER PRIMARY KEY,
                            round_id INTEGER NOT NULL,
                            user_id INTEGER,
                            script_type VARCHAR(20) NOT NULL,
                            text TEXT NOT NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'draft',
                            tone VARCHAR(200),
                            theme VARCHAR(200),
                            cue_position INTEGER,
                            quiz_date DATETIME,
                            selected BOOLEAN NOT NULL DEFAULT 0,
                            generated_mp3_path VARCHAR(500),
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                        """
                    )
                )
                changes_made = True

            if not _table_exists(inspector, "round_access_event"):
                conn.execute(
                    text(
                        """
                        CREATE TABLE round_access_event (
                            id INTEGER PRIMARY KEY,
                            round_id INTEGER NOT NULL,
                            actor_user_id INTEGER,
                            target_user_id INTEGER,
                            action VARCHAR(40) NOT NULL,
                            role VARCHAR(20),
                            details TEXT,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                changes_made = True

            inspector = inspect(db.engine)
            if _table_exists(inspector, "round_audio_script"):
                script_columns = _columns(inspector, "round_audio_script")
                if "cue_position" not in script_columns:
                    conn.execute(text("ALTER TABLE round_audio_script ADD COLUMN cue_position INTEGER"))
                    changes_made = True

            inspector = inspect(db.engine)
            for table_name, index_name, columns in (
                ("round", "idx_round_owner_created", ["user_id", "created_at"]),
                ("round_share", "idx_round_share_user", ["user_id", "role"]),
                (
                    "round_access_event",
                    "idx_round_access_event_round_created",
                    ["round_id", "created_at"],
                ),
                (
                    "round_access_event",
                    "idx_round_access_event_actor",
                    ["actor_user_id", "created_at"],
                ),
                (
                    "round_access_event",
                    "idx_round_access_event_target",
                    ["target_user_id", "created_at"],
                ),
                (
                    "round_audio_script",
                    "idx_round_audio_script_round_status",
                    ["round_id", "status", "script_type"],
                ),
                (
                    "round_audio_script",
                    "idx_round_audio_script_cue",
                    ["round_id", "script_type", "cue_position", "selected"],
                ),
                ("round_audio_script", "idx_round_audio_script_user", ["user_id", "created_at"]),
            ):
                if table_name not in set(inspector.get_table_names()):
                    continue
                existing_columns = _columns(inspector, table_name)
                if all(column in existing_columns for column in columns):
                    changes_made = _create_index(conn, inspector, table_name, index_name, columns) or changes_made

            if changes_made:
                conn.commit()

        return True if changes_made else None
    except Exception as exc:
        logger.error("Migration add_round_collaboration_and_audio_scripts failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
