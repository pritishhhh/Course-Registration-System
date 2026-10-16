import os
from contextlib import contextmanager

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row


@contextmanager
def transaction():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(503, "Database is not configured.")
    # One connection per transaction; Supavisor provides the server-side pool.
    # Never share a connection between request threads. Disable prepared statements
    # because transaction pooling can assign a different backend at each commit.
    options = {"sslmode": "require"} if os.getenv("VERCEL") else {}
    with psycopg.connect(dsn, connect_timeout=5, prepare_threshold=None,
                         row_factory=dict_row, **options) as conn:
        conn.execute("SET LOCAL statement_timeout = '8s'")
        conn.execute("SET LOCAL lock_timeout = '3s'")
        conn.execute("SET LOCAL ROLE registration_app")
        yield conn
    # psycopg commits on success, rolls back on failure, and always closes.
