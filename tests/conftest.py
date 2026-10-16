import os

import psycopg
import pytest


@pytest.fixture
def db_url():
    # Deliberately never fall back to the application's DATABASE_URL.
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL must point to a disposable initialized test database")
    if not psycopg.conninfo.conninfo_to_dict(dsn).get("dbname", "").endswith("_test"):
        pytest.fail("The disposable database name must end in _test")
    return dsn


@pytest.fixture
def database(db_url):
    with psycopg.connect(db_url) as conn:
        conn.execute("TRUNCATE registration_audit, enrollments, students, course_sections, courses, terms RESTART IDENTITY CASCADE")
        conn.execute("INSERT INTO terms(name) VALUES ('Test term')")
        conn.execute("INSERT INTO courses(course_code,title) VALUES ('TEST101','Test course')")
        conn.execute("INSERT INTO course_sections(course_id,term_id,section_code,capacity,waitlist_capacity) VALUES (1,1,'A',3,5)")
        conn.execute("INSERT INTO students(full_name,email) SELECT 'Student ' || i, 'student' || i || '@example.test' FROM generate_series(1,200) i")
    return db_url
