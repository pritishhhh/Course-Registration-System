"""Apply the initial PostgreSQL schema once; reject edited applied files.

New production schema changes belong in new numbered SQL migration files.
"""

import hashlib
import os
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / "db" / name for name in (
    "01_schema.sql", "02_procedures.sql", "03_triggers.sql"
)]


def main():
    database_url = os.environ["DATABASE_URL"]
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(73514701)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            for path in FILES:
                source = path.read_bytes()
                digest = hashlib.sha256(source).hexdigest()
                cursor.execute("SELECT sha256 FROM schema_migrations WHERE name = %s", [path.name])
                row = cursor.fetchone()
                if row:
                    if row[0] != digest:
                        raise RuntimeError(f"Applied schema file changed: {path.name}; add a new migration")
                    continue
                cursor.execute(source.decode("utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (name, sha256) VALUES (%s, %s)",
                    [path.name, digest],
                )
                print(f"Applied {path.name}")


if __name__ == "__main__":
    main()
