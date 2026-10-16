-- Lock order: section, term, enrollment. Use one section per transaction.
CREATE FUNCTION fn_register_safe(p_student_id INT, p_section_id INT)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    sec course_sections%ROWTYPE;
    existing_status enrollment_status;
    opens TIMESTAMPTZ;
    closes TIMESTAMPTZ;
    wl_count INT;
BEGIN
    SELECT * INTO sec FROM course_sections WHERE section_id = p_section_id FOR UPDATE;
    IF NOT FOUND THEN RETURN 'SECTION_NOT_FOUND'; END IF;
    PERFORM 1 FROM students WHERE student_id = p_student_id;
    IF NOT FOUND THEN RETURN 'STUDENT_NOT_FOUND'; END IF;
    -- A retry stays idempotent even after the section fills or registration closes.
    SELECT status INTO existing_status FROM enrollments
    WHERE student_id = p_student_id AND section_id = p_section_id
      AND status IN ('ENROLLED', 'WAITLISTED');
    IF FOUND THEN RETURN 'ALREADY_' || existing_status::TEXT; END IF;
    SELECT registration_opens_at, registration_closes_at INTO opens, closes
    FROM terms WHERE term_id = sec.term_id FOR SHARE;
    -- Evaluate after waiting for locks, not at transaction start.
    IF opens > clock_timestamp() THEN RETURN 'REGISTRATION_NOT_OPEN'; END IF;
    IF closes <= clock_timestamp() THEN RETURN 'REGISTRATION_CLOSED'; END IF;
    IF sec.seats_filled < sec.capacity THEN
        INSERT INTO enrollments (student_id, section_id, status)
        VALUES (p_student_id, p_section_id, 'ENROLLED');
        UPDATE course_sections SET seats_filled = seats_filled + 1 WHERE section_id = p_section_id;
        RETURN 'ENROLLED';
    END IF;
    SELECT count(*) INTO wl_count FROM enrollments
    WHERE section_id = p_section_id AND status = 'WAITLISTED';
    IF wl_count >= sec.waitlist_capacity THEN
        INSERT INTO registration_audit (section_id, student_id, action)
        VALUES (p_section_id, p_student_id, 'REJECTED_FULL');
        RETURN 'FULL_NO_WAITLIST';
    END IF;
    INSERT INTO enrollments (student_id, section_id, status, waitlist_position)
    VALUES (p_student_id, p_section_id, 'WAITLISTED', wl_count + 1);
    RETURN 'WAITLISTED';
END;
$$;
CREATE FUNCTION fn_drop_enrollment(p_student_id INT, p_section_id INT)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    target enrollments%ROWTYPE;
    promoted BIGINT;
BEGIN
    PERFORM 1 FROM course_sections WHERE section_id = p_section_id FOR UPDATE;
    IF NOT FOUND THEN RETURN 'SECTION_NOT_FOUND'; END IF;
    SELECT * INTO target FROM enrollments
    WHERE student_id = p_student_id AND section_id = p_section_id
      AND status IN ('ENROLLED', 'WAITLISTED') FOR UPDATE;
    IF NOT FOUND THEN RETURN 'NOT_ENROLLED'; END IF;
    UPDATE enrollments SET status = 'DROPPED', waitlist_position = NULL,
        decided_at = clock_timestamp() WHERE enrollment_id = target.enrollment_id;
    IF target.status = 'ENROLLED' THEN
        SELECT enrollment_id INTO promoted FROM enrollments
        WHERE section_id = p_section_id AND status = 'WAITLISTED'
        ORDER BY waitlist_position, enrollment_id LIMIT 1 FOR UPDATE;
        IF FOUND THEN
            UPDATE enrollments SET status = 'ENROLLED', waitlist_position = NULL,
                decided_at = clock_timestamp() WHERE enrollment_id = promoted;
            UPDATE enrollments SET waitlist_position = waitlist_position - 1
            WHERE section_id = p_section_id AND status = 'WAITLISTED';
        ELSE
            UPDATE course_sections SET seats_filled = seats_filled - 1 WHERE section_id = p_section_id;
        END IF;
    ELSE
        -- Only people behind the dropped student move forward.
        UPDATE enrollments SET waitlist_position = waitlist_position - 1
        WHERE section_id = p_section_id AND status = 'WAITLISTED'
          AND waitlist_position > target.waitlist_position;
    END IF;
    RETURN 'DROPPED';
END;
$$;
-- Link identities by the verified immutable auth subject, never by email.
CREATE FUNCTION fn_ensure_student(p_subject UUID, p_email TEXT)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE result INT;
BEGIN
    INSERT INTO students (auth_subject, full_name, email)
    VALUES (p_subject, left(split_part(p_email, '@', 1), 200), lower(p_email))
    ON CONFLICT (auth_subject) DO UPDATE SET email = EXCLUDED.email
    RETURNING student_id INTO result;
    RETURN result;
END;
$$;
