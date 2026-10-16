"""Upgrade the original schema in one transaction; take a database backup first."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def upgrade(dsn):
    with psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(19284710)")
        columns = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='students'").fetchall()
        if not columns or ("auth_subject",) in columns:
            raise RuntimeError("Expected the original repository schema; upgrade was not applied.")
        for filename in ("migrations/001_legacy_upgrade.sql", "02_procedures.sql", "03_triggers.sql", "05_security.sql", "06_metadata.sql"):
            conn.execute((ROOT / "db" / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("Set DATABASE_URL to the legacy database to upgrade.")
    upgrade(os.environ["DATABASE_URL"])
    print("Legacy schema upgraded successfully.")
