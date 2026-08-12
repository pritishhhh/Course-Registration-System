import os
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import psycopg2

DB_CONFIG = dict(
    host=os.environ.get("PGHOST", "localhost"),
    port=os.environ.get("PGPORT", "5432"),
    dbname=os.environ.get("PGDATABASE", "registration"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)

NUM_STUDENTS_TO_TRY = 200
NUM_THREADS = 50

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_target_section():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT s.section_id, s.capacity
            FROM course_sections s
            JOIN courses c ON c.course_id = s.course_id
            WHERE c.course_code = 'CS101' AND s.section_code = 'A'
        """)
        return cur.fetchone()

def get_student_ids(n):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT student_id FROM students ORDER BY student_id LIMIT %s", (n,))
        return [row[0] for row in cur.fetchall()]

def reset_section(section_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM registration_audit WHERE section_id = %s", (section_id,))
        cur.execute("DELETE FROM enrollments WHERE section_id = %s", (section_id,))
        cur.execute("UPDATE course_sections SET seats_filled = 0, version = 0 WHERE section_id = %s", (section_id,))
        conn.commit()

def naive_register(student_id, section_id):
    conn = get_conn()
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
        conn.close()

def safe_register(student_id, section_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT fn_register_safe(%s, %s)", (student_id, section_id))
            result = cur.fetchone()[0]
        conn.commit()
        return result
    finally:
        conn.close()

def run_load_test(label, register_fn, section_id, student_ids):
    print(f"\n=== {label}: {len(student_ids)} students racing for {NUM_THREADS} concurrent workers ===")
    results = Counter()
    start = time.time()

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as pool:
        futures = {pool.submit(register_fn, sid, section_id): sid for sid in student_ids}
        for fut in as_completed(futures):
            try:
                results[fut.result()] += 1
            except Exception as e:
                results[f"ERROR: {type(e).__name__}"] += 1

    elapsed = time.time() - start

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT capacity, seats_filled FROM course_sections WHERE section_id = %s", (section_id,))
        capacity, seats_filled = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM enrollments WHERE section_id = %s AND status = 'ENROLLED'",
            (section_id,),
        )
        actual_enrolled_rows = cur.fetchone()[0]

    print(f"  finished in {elapsed:.2f}s")
    print(f"  results: {dict(results)}")
    print(f"  section capacity: {capacity}")
    print(f"  seats_filled column says: {seats_filled}")
    print(f"  actual ENROLLED rows in enrollments table: {actual_enrolled_rows}")

    if seats_filled > capacity or actual_enrolled_rows > capacity:
        print(f"  \033[91m*** OVERBOOKED by {max(seats_filled, actual_enrolled_rows) - capacity} seat(s) ***\033[0m")
    else:
        print("  \033[92mNo overbooking.\033[0m")

    return seats_filled, actual_enrolled_rows, capacity

def main():
    section_id, capacity = get_target_section()
    student_ids = get_student_ids(NUM_STUDENTS_TO_TRY)
    print(f"Target section_id={section_id}, capacity={capacity}, students competing={len(student_ids)}")

    reset_section(section_id)
    run_load_test("NAIVE (no locking)", naive_register, section_id, student_ids)

    reset_section(section_id)
    run_load_test("SAFE (SELECT ... FOR UPDATE)", safe_register, section_id, student_ids)

if __name__ == "__main__":
    main()
