from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest


def query(dsn, sql, params=()):
    with psycopg.connect(dsn) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


def register(dsn, sid, section=1):
    return query(dsn, "SELECT fn_register_safe(%s,%s)", (sid, section))[0][0]


def drop(dsn, sid):
    return query(dsn, "SELECT fn_drop_enrollment(%s,1)", (sid,))[0][0]


def assert_invariants(dsn):
    assert query(dsn, "SELECT seats_filled FROM course_sections WHERE section_id=1")[0][0] == query(dsn, "SELECT count(*) FROM enrollments WHERE status='ENROLLED'")[0][0]
    positions = [r[0] for r in query(dsn, "SELECT waitlist_position FROM enrollments WHERE status='WAITLISTED' ORDER BY waitlist_position")]
    assert positions == list(range(1, len(positions)+1))


def test_burst_cannot_overbook(database):
    with ThreadPoolExecutor(max_workers=20) as executor:
        outcomes = Counter(executor.map(lambda sid: register(database, sid), range(1, 201)))
    assert outcomes == {"ENROLLED": 3, "WAITLISTED": 5, "FULL_NO_WAITLIST": 192}
    assert_invariants(database)


def test_duplicate_burst_is_idempotent(database):
    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = Counter(executor.map(lambda _: register(database, 1), range(40)))
    assert outcomes == {"ENROLLED": 1, "ALREADY_ENROLLED": 39}
    assert_invariants(database)


@pytest.mark.parametrize("leaving", [4, 5, 7])
def test_waitlist_drop_preserves_people_ahead(database, leaving):
    for sid in range(1, 9): register(database, sid)
    assert drop(database, leaving) == "DROPPED"
    assert_invariants(database)
    ordered = [r[0] for r in query(database, "SELECT student_id FROM enrollments WHERE status='WAITLISTED' ORDER BY waitlist_position")]
    assert ordered == [sid for sid in range(4, 9) if sid != leaving]
    assert register(database, leaving) == "WAITLISTED"
    assert_invariants(database)


def test_promotion_follows_persisted_queue(database):
    for sid in range(1, 9): register(database, sid)
    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(lambda sid: drop(database, sid), [1, 2, 3])) == ["DROPPED"]*3
    assert query(database, "SELECT student_id FROM enrollments WHERE status='ENROLLED' ORDER BY student_id") == [(4,), (5,), (6,)]
    assert_invariants(database)
    assert query(database, "SELECT count(*) FROM registration_audit WHERE action='PROMOTED_FROM_WAITLIST'") == [(3,)]


def test_retry_when_full_and_closed(database):
    for sid in range(1, 9): register(database, sid)
    query(database, "UPDATE terms SET registration_closes_at=clock_timestamp()-interval '1 second'")
    assert register(database, 1) == "ALREADY_ENROLLED"
    assert register(database, 4) == "ALREADY_WAITLISTED"
    assert register(database, 9) == "REGISTRATION_CLOSED"
    assert drop(database, 1) == "DROPPED"  # Withdrawal/promotion remain allowed after close.
    assert_invariants(database)


def test_opening_window_and_missing_records(database):
    assert register(database, 9999) == "STUDENT_NOT_FOUND"
    assert register(database, 1, 9999) == "SECTION_NOT_FOUND"
    query(database, "UPDATE terms SET registration_opens_at=clock_timestamp()+interval '1 hour'")
    assert register(database, 1) == "REGISTRATION_NOT_OPEN"
    assert drop(database, 1) == "NOT_ENROLLED"


def test_failed_transaction_rolls_back_all_changes(database):
    with pytest.raises(RuntimeError):
        with psycopg.connect(database) as conn:
            conn.execute("SELECT fn_register_safe(1,1)")
            raise RuntimeError("client failure")
    assert query(database, "SELECT count(*) FROM enrollments") == [(0,)]
    assert query(database, "SELECT count(*) FROM registration_audit") == [(0,)]
    assert_invariants(database)


def test_counter_drift_rejected_at_commit(database):
    with pytest.raises(psycopg.errors.CheckViolation):
        query(database, "UPDATE course_sections SET seats_filled=1 WHERE section_id=1")
    assert_invariants(database)


def test_direct_enrollment_cannot_bypass_counter(database):
    with pytest.raises(psycopg.errors.CheckViolation):
        query(database, "INSERT INTO enrollments(student_id,section_id,status) VALUES (1,1,'ENROLLED')")
    assert query(database, "SELECT count(*) FROM enrollments") == [(0,)]


def test_zero_waitlist_capacity(database):
    query(database, "UPDATE course_sections SET waitlist_capacity=0")
    for sid in range(1, 4): assert register(database, sid) == "ENROLLED"
    assert register(database, 4) == "FULL_NO_WAITLIST"
    assert drop(database, 1) == "DROPPED"
    assert register(database, 4) == "ENROLLED"
    assert_invariants(database)


def test_audit_is_single_event_and_append_only(database):
    register(database, 1)
    assert query(database, "SELECT action FROM registration_audit") == [("ENROLLED",)]
    with pytest.raises(psycopg.Error): query(database, "DELETE FROM registration_audit")


def test_server_role_cannot_write_tables_or_read_other_enrollments(database):
    register(database, 1); register(database, 2)
    with psycopg.connect(database) as conn:
        conn.execute("SET LOCAL ROLE registration_app")
        assert conn.execute("SELECT count(*) FROM enrollments").fetchone() == (0,)
        conn.execute("SELECT set_config('app.student_id','1',true)")
        assert conn.execute("SELECT student_id FROM enrollments").fetchall() == [(1,)]
        assert conn.execute("SELECT seats_filled FROM section_catalog").fetchall() == [(2,)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(database) as conn:
            conn.execute("SET LOCAL ROLE registration_app")
            conn.execute("UPDATE course_sections SET seats_filled=0")


def test_runtime_function_commits_with_rls(database):
    with psycopg.connect(database) as conn:
        conn.execute("SET LOCAL ROLE registration_app")
        assert conn.execute("SELECT fn_register_safe(1,1)").fetchone() == ("ENROLLED",)
    assert_invariants(database)


def test_auth_link_does_not_claim_existing_email(database):
    with pytest.raises(psycopg.errors.UniqueViolation):
        query(database, "SELECT fn_ensure_student('00000000-0000-0000-0000-000000000001','student1@example.test')")
    assert query(database, "SELECT auth_subject FROM students WHERE student_id=1") == [(None,)]


def test_mixed_registrations_and_drops(database):
    for sid in range(1, 9): register(database, sid)
    def mutate(sid):
        return drop(database, sid) if sid <= 8 else register(database, sid)
    with ThreadPoolExecutor(max_workers=16) as executor:
        outcomes = list(executor.map(mutate, range(1, 61)))
    assert len(outcomes) == 60
    assert_invariants(database)
    assert query(database, "SELECT seats_filled FROM course_sections") == [(3,)]
