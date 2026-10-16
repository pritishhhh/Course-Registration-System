"""Demonstrate check-then-act overbooking in isolated, unconstrained test tables."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg


def main():
    dsn = os.environ.get("TEST_DATABASE_URL", "")
    if not dsn or not psycopg.conninfo.conninfo_to_dict(dsn).get("dbname", "").endswith("_test"):
        raise SystemExit("Set TEST_DATABASE_URL to a disposable database ending in _test.")
    workers = 20
    barrier = Barrier(workers, timeout=30)
    with psycopg.connect(dsn) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS benchmark_naive")
        conn.execute("CREATE TABLE IF NOT EXISTS benchmark_naive.section (id INT PRIMARY KEY, capacity INT NOT NULL, filled INT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS benchmark_naive.enrollment (student_id INT PRIMARY KEY)")
        conn.execute("TRUNCATE benchmark_naive.section, benchmark_naive.enrollment")
        conn.execute("INSERT INTO benchmark_naive.section VALUES (1,1,0)")

    def attempt(student):
        with psycopg.connect(dsn, autocommit=True) as conn:
            capacity, filled = conn.execute("SELECT capacity,filled FROM benchmark_naive.section WHERE id=1").fetchone()
            # Every thread sees the same stale count before any writer proceeds.
            barrier.wait()
            if filled < capacity:
                conn.execute("INSERT INTO benchmark_naive.enrollment VALUES (%s)", (student,))
                conn.execute("UPDATE benchmark_naive.section SET filled=filled+1 WHERE id=1")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(attempt, range(workers)))
    with psycopg.connect(dsn) as conn:
        enrolled = conn.execute("SELECT count(*) FROM benchmark_naive.enrollment").fetchone()[0]
    assert enrolled == workers
    print(f"Unsafe isolated demo: {enrolled} enrollments for 1 seat. Production tables were not modified.")


if __name__ == "__main__":
    main()
