-- =========================================================
-- 02_procedures.sql
-- The concurrency-safe registration / drop logic.
--
-- Key idea: SELECT ... FOR UPDATE on the course_sections row turns every
-- concurrent "can I get a seat?" check into a queue. Whoever gets the row
-- lock first checks seats_filled < capacity and, still holding the lock,
-- writes both the enrollment row and the updated seat count in the SAME
-- transaction. No other transaction can read a stale seat count and act
-- on it, because it's blocked waiting for the lock -- not racing against it.
-- =========================================================

CREATE OR REPLACE FUNCTION fn_register_safe(p_student_id INT, p_section_id INT)
RETURNS TEXT AS $$
DECLARE
    v_capacity   INT;
    v_filled     INT;
    v_wl_cap     INT;
    v_wl_count   INT;
    v_next_pos   INT;
    v_opens_at   TIMESTAMPTZ;
    v_closes_at  TIMESTAMPTZ;
    v_course_id  INT;
    v_term_id    INT;
BEGIN
    -- Always lock the student before the section. This also serializes two
    -- requests by one student for different sections of the same course.
    PERFORM 1 FROM students WHERE student_id = p_student_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'STUDENT_NOT_FOUND';
    END IF;

    -- Competing students for one section queue on this row.
    SELECT s.capacity, s.seats_filled, s.waitlist_capacity,
           t.registration_opens_at, t.registration_closes_at,
           s.course_id, s.term_id
      INTO v_capacity, v_filled, v_wl_cap, v_opens_at, v_closes_at,
           v_course_id, v_term_id
      FROM course_sections s
      JOIN terms t ON t.term_id = s.term_id
     WHERE s.section_id = p_section_id
     FOR UPDATE OF s;

    IF NOT FOUND THEN
        RETURN 'SECTION_NOT_FOUND';
    END IF;

    -- Return the existing outcome even when the section and waitlist are full.
    IF EXISTS (
        SELECT 1 FROM enrollments
        WHERE student_id = p_student_id AND section_id = p_section_id
          AND status IN ('ENROLLED', 'WAITLISTED')
    ) THEN
        RETURN 'ALREADY_REGISTERED';
    END IF;

    -- One active section per course and term. The student row lock makes this
    -- check safe even when the requests target two different section rows.
    IF EXISTS (
        SELECT 1 FROM enrollments e
        JOIN course_sections other ON other.section_id = e.section_id
        WHERE e.student_id = p_student_id
          AND e.status IN ('ENROLLED', 'WAITLISTED')
          AND other.course_id = v_course_id AND other.term_id = v_term_id
    ) THEN
        RETURN 'ALREADY_IN_COURSE';
    END IF;

    IF (v_opens_at IS NOT NULL AND clock_timestamp() < v_opens_at)
       OR (v_closes_at IS NOT NULL AND clock_timestamp() >= v_closes_at) THEN
        RETURN 'REGISTRATION_CLOSED';
    END IF;

    -- Seat available -> enroll directly.
    IF v_filled < v_capacity THEN
        BEGIN
            INSERT INTO enrollments (student_id, section_id, status, decided_at)
            VALUES (p_student_id, p_section_id, 'ENROLLED', clock_timestamp());
        EXCEPTION WHEN unique_violation THEN
            RETURN 'ALREADY_REGISTERED';
        END;

        UPDATE course_sections
           SET seats_filled = seats_filled + 1,
               version = version + 1
         WHERE section_id = p_section_id;

        INSERT INTO registration_audit (section_id, student_id, action, detail)
        VALUES (p_section_id, p_student_id, 'ENROLLED',
                jsonb_build_object('seats_filled_after', v_filled + 1, 'capacity', v_capacity));

        RETURN 'ENROLLED';
    END IF;

    -- Section full -> try the waitlist.
    SELECT count(*) INTO v_wl_count
      FROM enrollments
     WHERE section_id = p_section_id AND status = 'WAITLISTED';

    IF v_wl_count >= v_wl_cap THEN
        INSERT INTO registration_audit (section_id, student_id, action, detail)
        VALUES (p_section_id, p_student_id, 'REJECTED_FULL', jsonb_build_object('reason', 'section and waitlist full'));
        RETURN 'FULL_NO_WAITLIST';
    END IF;

    v_next_pos := v_wl_count + 1;

    BEGIN
        INSERT INTO enrollments (student_id, section_id, status, waitlist_position, decided_at)
        VALUES (p_student_id, p_section_id, 'WAITLISTED', v_next_pos, clock_timestamp());
    EXCEPTION WHEN unique_violation THEN
        RETURN 'ALREADY_REGISTERED';
    END;

    INSERT INTO registration_audit (section_id, student_id, action, detail)
    VALUES (p_section_id, p_student_id, 'WAITLISTED', jsonb_build_object('position', v_next_pos));

    RETURN 'WAITLISTED';
END;
$$ LANGUAGE plpgsql;


-- Dropping a seat and promoting the next waitlisted student happens
-- atomically under the same row lock, so a promoted student can never be
-- "double promoted" by two concurrent drops.
CREATE OR REPLACE FUNCTION fn_drop_enrollment(p_student_id INT, p_section_id INT)
RETURNS TEXT AS $$
DECLARE
    v_status         enrollment_status;
    v_promoted_id    INT;
    v_promoted_student INT;
    v_dropped_position INT;
BEGIN
    PERFORM 1 FROM students WHERE student_id = p_student_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'STUDENT_NOT_FOUND';
    END IF;

    PERFORM 1 FROM course_sections WHERE section_id = p_section_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'SECTION_NOT_FOUND';
    END IF;

    SELECT status, waitlist_position INTO v_status, v_dropped_position
      FROM enrollments
     WHERE student_id = p_student_id
       AND section_id = p_section_id
       AND status IN ('ENROLLED', 'WAITLISTED')
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'NOT_ENROLLED';
    END IF;

    UPDATE enrollments
       SET status = 'DROPPED', waitlist_position = NULL,
           decided_at = clock_timestamp()
     WHERE student_id = p_student_id AND section_id = p_section_id
       AND status = v_status;

    IF v_status = 'ENROLLED' THEN
        UPDATE course_sections
           SET seats_filled = seats_filled - 1,
               version = version + 1
         WHERE section_id = p_section_id;

        INSERT INTO registration_audit (section_id, student_id, action)
        VALUES (p_section_id, p_student_id, 'DROPPED_ENROLLED');

        -- Promote the earliest waitlisted student, if any.
        SELECT enrollment_id, student_id INTO v_promoted_id, v_promoted_student
          FROM enrollments
         WHERE section_id = p_section_id AND status = 'WAITLISTED'
         ORDER BY waitlist_position ASC
         LIMIT 1
         FOR UPDATE;

        IF FOUND THEN
            UPDATE enrollments
               SET status = 'ENROLLED', waitlist_position = NULL, decided_at = clock_timestamp()
             WHERE enrollment_id = v_promoted_id;

            UPDATE course_sections
               SET seats_filled = seats_filled + 1,
                   version = version + 1
             WHERE section_id = p_section_id;

            -- Close the gap in waitlist positions for everyone behind them.
            UPDATE enrollments
               SET waitlist_position = waitlist_position - 1
             WHERE section_id = p_section_id
               AND status = 'WAITLISTED';

            INSERT INTO registration_audit (section_id, student_id, action, detail)
            VALUES (p_section_id, v_promoted_student, 'PROMOTED_FROM_WAITLIST',
                    jsonb_build_object('vacated_by', p_student_id));
        END IF;
    ELSE
        -- Only students behind the dropped position move forward.
        UPDATE enrollments
           SET waitlist_position = waitlist_position - 1
         WHERE section_id = p_section_id
           AND status = 'WAITLISTED'
           AND waitlist_position > v_dropped_position;

        INSERT INTO registration_audit (section_id, student_id, action)
        VALUES (p_section_id, p_student_id, 'DROPPED_WAITLIST');
    END IF;

    RETURN 'DROPPED';
END;
$$ LANGUAGE plpgsql;


-- Optimistic-locking alternative, kept for comparison (see README).
-- Instead of taking a row lock, it reads the version, then does a
-- conditional UPDATE that only succeeds if the version hasn't changed.
-- The CALLER is responsible for retrying on 'CONFLICT_RETRY'.
CREATE OR REPLACE FUNCTION fn_register_optimistic(p_student_id INT, p_section_id INT)
RETURNS TEXT AS $$
DECLARE
    v_capacity INT;
    v_filled   INT;
    v_version  INT;
    v_rows     INT;
BEGIN
    SELECT capacity, seats_filled, version
      INTO v_capacity, v_filled, v_version
      FROM course_sections
     WHERE section_id = p_section_id;

    IF NOT FOUND THEN
        RETURN 'SECTION_NOT_FOUND';
    END IF;

    IF v_filled >= v_capacity THEN
        RETURN 'FULL';
    END IF;

    UPDATE course_sections
       SET seats_filled = seats_filled + 1,
           version = version + 1
     WHERE section_id = p_section_id
       AND version = v_version;      -- fails silently if someone else won the race

    GET DIAGNOSTICS v_rows = ROW_COUNT;

    IF v_rows = 0 THEN
        RETURN 'CONFLICT_RETRY';
    END IF;

    BEGIN
        INSERT INTO enrollments (student_id, section_id, status, decided_at)
        VALUES (p_student_id, p_section_id, 'ENROLLED', clock_timestamp());
    EXCEPTION WHEN unique_violation THEN
        -- roll back the seat we just claimed
        UPDATE course_sections SET seats_filled = seats_filled - 1 WHERE section_id = p_section_id;
        RETURN 'ALREADY_ENROLLED';
    END;

    RETURN 'ENROLLED';
END;
$$ LANGUAGE plpgsql;
