-- The API assumes this non-login role within each transaction.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'registration_app') THEN
        CREATE ROLE registration_app NOLOGIN;
    END IF;
END $$;
GRANT registration_app TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO registration_app;
-- This owner-backed view exposes aggregate availability without student records.
CREATE VIEW section_catalog WITH (security_barrier = true) AS
SELECT s.section_id, s.term_id, s.section_code, s.instructor, s.capacity,
    s.seats_filled, s.waitlist_capacity, c.course_code, c.title, c.credits,
    t.name AS term, t.registration_opens_at, t.registration_closes_at,
    (SELECT count(*) FROM enrollments e WHERE e.section_id = s.section_id
        AND e.status = 'WAITLISTED') AS waitlist_filled
FROM course_sections s JOIN courses c USING (course_id) JOIN terms t USING (term_id);
REVOKE ALL ON section_catalog FROM PUBLIC;
GRANT SELECT ON section_catalog TO registration_app;
GRANT SELECT ON courses, terms, course_sections, enrollments TO registration_app;
GRANT EXECUTE ON FUNCTION fn_register_safe(INT, INT), fn_drop_enrollment(INT, INT),
    fn_ensure_student(UUID, TEXT) TO registration_app;
-- Block Supabase Data API/RPC from bypassing the authenticated server.
REVOKE ALL ON students, courses, terms, course_sections, enrollments, registration_audit FROM PUBLIC;
REVOKE ALL ON FUNCTION fn_register_safe(INT, INT), fn_drop_enrollment(INT, INT),
    fn_ensure_student(UUID, TEXT), trg_section_invariants(), trg_enrollment_audit(),
    trg_audit_immutable() FROM PUBLIC;
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE registration_audit ENABLE ROW LEVEL SECURITY;
CREATE POLICY server_read_courses ON courses FOR SELECT TO registration_app USING (true);
CREATE POLICY server_read_terms ON terms FOR SELECT TO registration_app USING (true);
CREATE POLICY server_read_sections ON course_sections FOR SELECT TO registration_app USING (true);
CREATE POLICY server_read_enrollments ON enrollments FOR SELECT TO registration_app
    USING (student_id = nullif(current_setting('app.student_id', true), '')::INT);
DO $$ DECLARE role_name TEXT; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON students, courses, terms, course_sections, enrollments, registration_audit, section_catalog FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION fn_register_safe(INT, INT), fn_drop_enrollment(INT, INT), fn_ensure_student(UUID, TEXT), trg_section_invariants(), trg_enrollment_audit(), trg_audit_immutable() FROM %I', role_name);
        END IF;
    END LOOP;
END $$;
