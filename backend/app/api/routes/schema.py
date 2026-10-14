from __future__ import annotations

from typing import Any


def fetch_schema_metadata() -> list[dict[str, Any]]:
    from app.core.config import get_settings
    from app.db.connection import check_database_connection
    import psycopg

    settings = get_settings()
    check_database_connection()

    with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            tables = cur.fetchall()
            metadata: list[dict[str, Any]] = []

            for (table_name,) in tables:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table_name,),
                )
                columns = cur.fetchall()

                cur.execute(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = %s
                      AND tc.constraint_type = 'PRIMARY KEY'
                    ORDER BY kcu.ordinal_position
                    """,
                    (table_name,),
                )
                primary_keys = [column_name for (column_name,) in cur.fetchall()]

                cur.execute(
                    """
                    SELECT kcu.column_name, ccu.table_name, ccu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage ccu
                      ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = %s
                      AND tc.constraint_type = 'FOREIGN KEY'
                    """,
                    (table_name,),
                )
                foreign_keys = [
                    {
                        "column": row[0],
                        "references_table": row[1],
                        "references_column": row[2],
                    }
                    for row in cur.fetchall()
                ]

                metadata.append(
                    {
                        "name": table_name,
                        "columns": [
                            {
                                "name": column_name,
                                "type": data_type,
                                "nullable": is_nullable == "YES",
                                "is_primary_key": column_name in primary_keys,
                            }
                            for column_name, data_type, is_nullable in columns
                        ],
                        "primary_keys": primary_keys,
                        "foreign_keys": foreign_keys,
                    }
                )

    return metadata