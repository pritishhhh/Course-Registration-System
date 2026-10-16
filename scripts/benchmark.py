"""Threaded benchmark against a disposable database, with correctness assertions."""
import os
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import psycopg


def positive(name, default, maximum):
    value = int(os.getenv(name) or default)
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def main(single=False):
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn or not psycopg.conninfo.conninfo_to_dict(dsn).get("dbname", "").endswith("_test"):
        raise SystemExit("Set TEST_DATABASE_URL to an initialized disposable database ending in _test. This script resets test data.")
    students = positive("NUM_STUDENTS_TO_TRY", 200, 20000)
    threads = positive("NUM_THREADS", 20, 80)
    subjects = 1 if single else positive("NUM_SUBJECTS", 4, 4)
    capacity = positive("SUBJECT_CAPACITY", 30, 20000)
    per_student = min(positive("NUM_COURSES_PER_STUDENT", 2, 4), subjects)
    with psycopg.connect(dsn) as conn:
        conn.execute("TRUNCATE registration_audit, enrollments, students, course_sections, courses, terms RESTART IDENTITY CASCADE")
        conn.execute("INSERT INTO terms(name) VALUES ('Benchmark')")
        conn.execute("INSERT INTO courses(course_code,title) SELECT 'LOAD' || i, 'Benchmark ' || i FROM generate_series(1,%s) i", (subjects,))
        conn.execute("INSERT INTO course_sections(course_id,term_id,section_code,capacity,waitlist_capacity) SELECT course_id,1,'A',%s,15 FROM courses", (capacity,))
        conn.execute("INSERT INTO students(full_name,email) SELECT 'Student ' || i, 'load' || i || '@example.test' FROM generate_series(1,%s) i", (students,))
    rng = random.Random(42)
    targets = [(sid, sec) for sid in range(1, students+1) for sec in rng.sample(range(1, subjects+1), per_student)]

    def register(target):
        # No connection is reused across threads or returned in aborted state.
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            conn.execute("SET LOCAL statement_timeout='30s'")
            return conn.execute("SELECT fn_register_safe(%s,%s)", target).fetchone()[0]

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as executor:
        # Any worker exception propagates and fails CI.
        outcomes = Counter(executor.map(register, targets))
    print(f"{len(targets)} requests, {threads} workers, {time.perf_counter()-start:.2f}s: {dict(outcomes)}")
    with psycopg.connect(dsn) as conn:
        for sec, cap, filled in conn.execute("SELECT section_id,capacity,seats_filled FROM course_sections ORDER BY section_id").fetchall():
            enrolled = conn.execute("SELECT count(*) FROM enrollments WHERE section_id=%s AND status='ENROLLED'", (sec,)).fetchone()[0]
            positions = [r[0] for r in conn.execute("SELECT waitlist_position FROM enrollments WHERE section_id=%s AND status='WAITLISTED' ORDER BY waitlist_position", (sec,))]
            attempts = sum(target[1] == sec for target in targets)
            assert filled == enrolled == min(cap, attempts), (sec, filled, enrolled, cap, attempts)
            assert positions == list(range(1, min(15, max(0, attempts-cap))+1)), (sec, positions)
            print(f"Section {sec}: enrolled={enrolled}/{cap}, waitlisted={len(positions)}; invariants passed")


if __name__ == "__main__":
    main()
