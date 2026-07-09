"""Add quizmaster profile preferences used by planning agents."""

import logging

from sqlalchemy import inspect, text


PROFILE_COLUMNS = {
    "default_language": "VARCHAR(16) DEFAULT 'de'",
    "tone": "VARCHAR(200) DEFAULT 'warm, concise, lightly humorous'",
    "tts_voice": "VARCHAR(120)",
    "email_recipient": "VARCHAR(120)",
    "preferred_genres": "TEXT",
    "preferred_decades": "TEXT",
    "banned_artists": "TEXT",
    "banned_songs": "TEXT",
    "repeat_cooldown_weeks": "INTEGER DEFAULT 12 NOT NULL",
    "timezone": "VARCHAR(64) DEFAULT 'Europe/Berlin' NOT NULL",
}


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        dialect = db.engine.dialect.name
        existing_columns = {
            column["name"] for column in inspector.get_columns("user_preferences")
        }
        existing_tables = set(inspector.get_table_names())
        has_user_table = "user" in existing_tables
        missing_columns = [
            (name, definition)
            for name, definition in PROFILE_COLUMNS.items()
            if name not in existing_columns
        ]
        changed = False

        with db.engine.connect() as conn:
            for name, definition in missing_columns:
                conn.execute(
                    text(f"ALTER TABLE user_preferences ADD COLUMN {name} {definition}")
                )
                changed = True
            changed = changed or conn.execute(
                text(
                    "UPDATE user_preferences "
                    "SET default_language = COALESCE(default_language, 'de'), "
                    "tone = COALESCE(tone, 'warm, concise, lightly humorous'), "
                    "repeat_cooldown_weeks = COALESCE(repeat_cooldown_weeks, 12), "
                    "timezone = COALESCE(NULLIF(TRIM(timezone), ''), 'Europe/Berlin') "
                    "WHERE default_language IS NULL "
                    "OR tone IS NULL "
                    "OR repeat_cooldown_weeks IS NULL "
                    "OR timezone IS NULL "
                    "OR TRIM(timezone) = ''"
                )
            ).rowcount > 0
            if has_user_table:
                changed = changed or conn.execute(
                    text(
                        'INSERT INTO user_preferences '
                        "(user_id, default_language, tone, repeat_cooldown_weeks, timezone) "
                        'SELECT u.id, '
                        "'de', "
                        "'warm, concise, lightly humorous', "
                        "12, "
                        "'Europe/Berlin' "
                        'FROM "user" u '
                        "WHERE NOT EXISTS ("
                        "SELECT 1 FROM user_preferences p WHERE p.user_id = u.id"
                        ")"
                    )
                ).rowcount > 0
            if "timezone" in existing_columns or any(
                name == "timezone" for name, _definition in missing_columns
            ):
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE user_preferences "
                            "ALTER COLUMN timezone SET DEFAULT 'Europe/Berlin'"
                        )
                    )
                    conn.execute(
                        text(
                            "ALTER TABLE user_preferences "
                            "ALTER COLUMN timezone SET NOT NULL"
                        )
                    )
            conn.commit()

        if not changed:
            logging.info("No changes were needed")
            return None

        logging.info("Migration add_quizmaster_profile_preferences completed successfully")
        return True
    except Exception as exc:
        logging.error("Migration add_quizmaster_profile_preferences failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
