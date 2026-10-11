import psycopg
from app.core.config import get_settings


def check_database_connection() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, connect_timeout=3) as connection:
        connection.execute("SELECT 1")
