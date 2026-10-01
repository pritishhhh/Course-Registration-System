import os
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import psycopg2
from psycopg2 import pool

DB_CONFIG = dict(
    host=os.environ.get("PGHOST", "localhost"),
    port=os.environ.get("PGPORT", "5432"),
    dbname=os.environ.get("PGDATABASE", "registration"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)

NUM_STUDENTS_TO_TRY = int(os.environ.get("NUM_STUDENTS_TO_TRY", "200"))
NUM_SUBJECTS = int(os.environ.get("NUM_SUBJECTS", "4"))
SUBJECT_CAPACITY = int(os.environ.get("SUBJECT_CAPACITY", "0"))
NUM_COURSES_PER_STUDENT = int(os.environ.get("NUM_COURSES_PER_STUDENT", "2"))
NUM_THREADS = int(os.environ.get("NUM_THREADS", "50"))

db_pool = pool.ThreadedConnectionPool(1, NUM_THREADS, **DB_CONFIG)

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_all_sections():
    with get_conn() as conn, conn.cursor() as cur:
        if SUBJECT_CAPACITY > 0:
            cur.execute("UPDATE course_sections SET capacity = %s", (SUBJECT_CAPACITY,))
            conn.commit()
            
        cur.execute("""
            SELECT s.section_id, s.capacity, c.course_code
            FROM course_sections s
            JOIN courses c ON c.course_id = s.course_id
            ORDER BY s.section_id
            LIMIT %s
        """, (NUM_SUBJECTS,))
        return cur.fetchall()

def get_student_ids(n):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM students")
        current_count = cur.fetchone()[0]
        if current_count < n:
            print(f"Seeding {n - current_count} more students to the database... this takes just a second.")
            cur.execute(
                "INSERT INTO students (full_name, email) "
                "SELECT 'Student ' || i, 'student' || i || '@university.edu' "
                "FROM generate_series(%s, %s) AS i",
                (current_count + 1, n)
            )
            conn.commit()

        cur.execute("SELECT student_id FROM students ORDER BY student_id LIMIT %s", (n,))
        return [row[0] for row in cur.fetchall()]

def reset_all_sections():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM registration_audit")
        cur.execute("DELETE FROM enrollments")
        cur.execute("UPDATE course_sections SET seats_filled = 0, version = 0")
        conn.commit()

def naive_register(student_id, section_id):
    conn = db_pool.getconn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT capacity, seats_filled FROM course_sections WHERE section_id = %s",
                (section_id,),
            )
            capacity, filled = cur.fetchone()

            time.sleep(random.uniform(0.001, 0.01))

            if filled < capacity:
                cur.execute(
                    """INSERT INTO enrollments (student_id, section_id, status, decided_at)
                       VALUES (%s, %s, 'ENROLLED', clock_timestamp())
                       ON CONFLICT DO NOTHING""",
                    (student_id, section_id),
                )
                cur.execute(
                    "UPDATE course_sections SET seats_filled = seats_filled + 1 WHERE section_id = %s",
                    (section_id,),
                )
                return "ENROLLED"
            else:
                return "FULL"
    finally:
        db_pool.putconn(conn)

def safe_register(student_id, section_id):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT fn_register_safe(%s, %s)", (student_id, section_id))
            result = cur.fetchone()[0]
        conn.commit()
        return result
    finally:
        db_pool.putconn(conn)

def run_load_test(label, register_fn, student_targets, sections):
    print(f"\n=== {label}: {len(student_targets)} registration attempts across {len(sections)} courses ===")
    results = Counter()
    start = time.time()

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as pool_exec:
        futures = {pool_exec.submit(register_fn, sid, sec_id): (sid, sec_id) for sid, sec_id in student_targets}
        for fut in as_completed(futures):
            try:
                results[fut.result()] += 1
            except Exception as e:
                results[f"ERROR: {type(e).__name__}"] += 1

    elapsed = time.time() - start
    print(f"  finished in {elapsed:.2f}s")
    print(f"  results: {dict(results)}")
    
    overbooked = False
    with get_conn() as conn, conn.cursor() as cur:
        for sec_id, capacity, code in sections:
            cur.execute("SELECT seats_filled FROM course_sections WHERE section_id = %s", (sec_id,))
            seats_filled = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM enrollments WHERE section_id = %s AND status = 'ENROLLED'",
                (sec_id,),
            )
            actual_enrolled = cur.fetchone()[0]

            if seats_filled > capacity or actual_enrolled > capacity:
                diff = max(seats_filled, actual_enrolled) - capacity
                print(f"  \033[91m*** {code} OVERBOOKED by {diff} seat(s) (Cap: {capacity}, Enrolled: {actual_enrolled}) ***\033[0m")
                overbooked = True
            else:
                print(f"  \033[92m{code} OK (Cap: {capacity}, Enrolled: {actual_enrolled})\033[0m")

    if not overbooked:
        print("  \033[92mNo overbooking globally.\033[0m")

def main():
    sections = get_all_sections()
    section_ids = [s[0] for s in sections]
    student_ids = get_student_ids(NUM_STUDENTS_TO_TRY)
    
    student_targets = []
    actual_courses_per_student = min(NUM_COURSES_PER_STUDENT, len(section_ids))
    for sid in student_ids:
        chosen_sections = random.sample(section_ids, actual_courses_per_student)
        for sec_id in chosen_sections:
            student_targets.append((sid, sec_id))
            
    print(f"Targeting {len(sections)} sections. {len(student_ids)} students making {len(student_targets)} total attempts.")

    reset_all_sections()
    run_load_test("NAIVE (no locking)", naive_register, student_targets, sections)

    reset_all_sections()
    run_load_test("SAFE (SELECT ... FOR UPDATE)", safe_register, student_targets, sections)

if __name__ == "__main__":
    main()
