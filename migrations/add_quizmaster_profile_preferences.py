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
}


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = {
            column["name"] for column in inspector.get_columns("user_preferences")
        }
        missing_columns = [
            (name, definition)
            for name, definition in PROFILE_COLUMNS.items()
            if name not in existing_columns
        ]
        if not missing_columns:
            logging.info("No changes were needed")
            return None

        with db.engine.connect() as conn:
            for name, definition in missing_columns:
                conn.execute(
                    text(f"ALTER TABLE user_preferences ADD COLUMN {name} {definition}")
                )
            conn.execute(
                text(
                    "UPDATE user_preferences "
                    "SET default_language = COALESCE(default_language, 'de'), "
                    "tone = COALESCE(tone, 'warm, concise, lightly humorous'), "
                    "repeat_cooldown_weeks = COALESCE(repeat_cooldown_weeks, 12)"
                )
            )
            conn.commit()

        logging.info("Migration add_quizmaster_profile_preferences completed successfully")
        return True
    except Exception as exc:
        logging.error("Migration add_quizmaster_profile_preferences failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
