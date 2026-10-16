"""Initialize an empty database. Existing schemas are never overwritten."""
import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def initialize(dsn, seed=False):
    with psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None) as conn:
        # One transaction: a SQL failure rolls back the entire installation.
        conn.execute("SELECT pg_advisory_xact_lock(19284710)")
        if conn.execute("SELECT to_regclass('public.students')").fetchone()[0]:
            raise RuntimeError("Database already contains students. Use a new database or the documented legacy upgrade.")
        for filename in ("01_schema.sql", "02_procedures.sql", "03_triggers.sql", "05_security.sql", "06_metadata.sql"):
            conn.execute((ROOT / "db" / filename).read_text(encoding="utf-8"))
        if seed:
            conn.execute((ROOT / "db" / "04_seed.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="Add the example course catalog")
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL"):
        parser.error("Set DATABASE_URL in the environment or .env")
    initialize(os.environ["DATABASE_URL"], args.seed)
    print("Database initialized successfully.")
