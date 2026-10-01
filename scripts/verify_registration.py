"""Fail CI if concurrent registration breaks capacity or waitlist invariants.

Run only against a disposable database: this resets the CS101-A section.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import psycopg2


DB = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "registration"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", "postgres"),
)


def query(sql, params=()):
    with closing(psycopg2.connect(**DB)) as conn, conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None


def register(student_id, section_id):
    return query("SELECT fn_register_safe(%s, %s)", (student_id, section_id))[0][0]


def drop(student_id, section_id):
    return query("SELECT fn_drop_enrollment(%s, %s)", (student_id, section_id))[0][0]


def check(section_id, capacity, waitlist_capacity):
    rows = query(
        """SELECT status::text, count(*) FROM enrollments
           WHERE section_id = %s AND status IN ('ENROLLED', 'WAITLISTED')
           GROUP BY status""",
        (section_id,),
    )
    counts = dict(rows)
    filled = query("SELECT seats_filled FROM course_sections WHERE section_id = %s", (section_id,))[0][0]
    positions = [row[0] for row in query(
        """SELECT waitlist_position FROM enrollments
           WHERE section_id = %s AND status = 'WAITLISTED'
           ORDER BY waitlist_position""",
        (section_id,),
    )]
    assert filled == counts.get("ENROLLED", 0) <= capacity, (filled, counts)
    assert counts.get("WAITLISTED", 0) <= waitlist_capacity, counts
    assert positions == list(range(1, len(positions) + 1)), positions


def main():
    section_id = query(
        """SELECT s.section_id FROM course_sections s JOIN courses c USING (course_id)
           WHERE c.course_code = 'CS101' AND s.section_code = 'A'"""
    )[0][0]
    query("DELETE FROM registration_audit WHERE section_id = %s", (section_id,))
    query("DELETE FROM enrollments WHERE section_id = %s", (section_id,))
    query(
        "UPDATE course_sections SET seats_filled = 0, capacity = 5, waitlist_capacity = 10 WHERE section_id = %s",
        (section_id,),
    )
    student_ids = [row[0] for row in query("SELECT student_id FROM students ORDER BY student_id LIMIT 80")]
    assert len(student_ids) == 80, "Seed at least 80 students"

    with ThreadPoolExecutor(max_workers=40) as executor:
        results = list(executor.map(lambda student_id: register(student_id, section_id), student_ids))
    assert results.count("ENROLLED") == 5, results
    assert results.count("WAITLISTED") == 10, results
    assert results.count("FULL_NO_WAITLIST") == 65, results
    check(section_id, 5, 10)

    waitlist = query(
        """SELECT student_id FROM enrollments WHERE section_id = %s
           AND status = 'WAITLISTED' ORDER BY waitlist_position""",
        (section_id,),
    )
    middle_student = waitlist[4][0]
    assert register(middle_student, section_id) == "ALREADY_REGISTERED"
    assert drop(middle_student, section_id) == "DROPPED"
    assert drop(middle_student, section_id) == "NOT_ENROLLED"
    check(section_id, 5, 10)

    enrolled = query(
        """SELECT student_id FROM enrollments WHERE section_id = %s
           AND status = 'ENROLLED' LIMIT 1""",
        (section_id,),
    )[0][0]
    first_waitlisted = waitlist[0][0]
    assert drop(enrolled, section_id) == "DROPPED"
    assert query(
        """SELECT status::text FROM enrollments WHERE section_id = %s
           AND student_id = %s AND status = 'ENROLLED'""",
        (section_id, first_waitlisted),
    ) == [("ENROLLED",)]
    check(section_id, 5, 10)

    assert register(2147483647, section_id) == "STUDENT_NOT_FOUND"
    query(
        """UPDATE terms SET registration_opens_at = now() - interval '2 days',
           registration_closes_at = now() - interval '1 minute'
           WHERE term_id = (SELECT term_id FROM course_sections WHERE section_id = %s)""",
        (section_id,),
    )
    assert register(student_ids[-1], section_id) == "REGISTRATION_CLOSED"
    assert register(first_waitlisted, section_id) == "ALREADY_REGISTERED"
    query(
        """UPDATE terms SET registration_opens_at = now() - interval '1 minute',
           registration_closes_at = now() + interval '14 days'
           WHERE term_id = (SELECT term_id FROM course_sections WHERE section_id = %s)""",
        (section_id,),
    )
    print("PASS: concurrent capacity, duplicate, waitlist order, promotion, and window checks")


if __name__ == "__main__":
    main()
