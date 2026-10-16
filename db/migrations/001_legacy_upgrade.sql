-- Upgrade only the original repository schema. The Python runner wraps this and
-- the replacement functions, triggers, and permissions in one transaction.
LOCK TABLE students, courses, terms, course_sections, enrollments, registration_audit IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT FROM course_sections s WHERE
        (SELECT count(*) FROM enrollments e WHERE e.section_id=s.section_id AND e.status='ENROLLED') > s.capacity
        OR (SELECT count(*) FROM enrollments e WHERE e.section_id=s.section_id AND e.status='WAITLISTED') > s.waitlist_capacity) THEN
        RAISE EXCEPTION 'Legacy data exceeds capacity. Resolve overbooking before upgrading; no student is removed automatically.';
    END IF;
END $$;
DROP TRIGGER IF EXISTS enrollment_audit ON enrollments;
DROP TRIGGER IF EXISTS section_capacity_guard ON course_sections;
DROP FUNCTION IF EXISTS trg_enrollment_audit();
DROP FUNCTION IF EXISTS trg_check_capacity();
DROP FUNCTION IF EXISTS fn_register_safe(INT,INT);
DROP FUNCTION IF EXISTS fn_drop_enrollment(INT,INT);
DROP FUNCTION IF EXISTS fn_register_optimistic(INT,INT);
ALTER TABLE students ADD COLUMN auth_subject UUID UNIQUE;
ALTER TABLE students ADD CHECK (length(trim(full_name)) BETWEEN 1 AND 200);
ALTER TABLE students ADD CHECK (length(email) BETWEEN 3 AND 320);
ALTER TABLE courses ADD CHECK (credits > 0);
ALTER TABLE terms ADD UNIQUE (name);
ALTER TABLE terms ADD CHECK (registration_closes_at > registration_opens_at);
ALTER TABLE course_sections DROP COLUMN version;
ALTER TABLE course_sections ADD CHECK (waitlist_capacity >= 0);
UPDATE enrollments SET waitlist_position=NULL WHERE status <> 'WAITLISTED';
WITH ordered AS (
    SELECT enrollment_id, row_number() OVER (PARTITION BY section_id ORDER BY waitlist_position NULLS LAST, enrollment_id) AS pos
    FROM enrollments WHERE status='WAITLISTED'
)
UPDATE enrollments e SET waitlist_position=o.pos FROM ordered o WHERE e.enrollment_id=o.enrollment_id;
UPDATE course_sections s SET seats_filled=(SELECT count(*) FROM enrollments e WHERE e.section_id=s.section_id AND e.status='ENROLLED');
-- Inconsistent free seats with a queue need an explicit operator decision.
DO $$ BEGIN
    IF EXISTS (SELECT FROM course_sections s WHERE seats_filled < capacity
        AND EXISTS (SELECT FROM enrollments e WHERE e.section_id=s.section_id AND e.status='WAITLISTED')) THEN
        RAISE EXCEPTION 'Legacy waitlist has vacant seats. Resolve promotions before upgrading.';
    END IF;
END $$;
UPDATE enrollments SET decided_at=coalesce(decided_at,requested_at);
ALTER TABLE enrollments ALTER COLUMN decided_at SET DEFAULT clock_timestamp();
ALTER TABLE enrollments ALTER COLUMN decided_at SET NOT NULL;
ALTER TABLE enrollments ADD CHECK ((status='WAITLISTED' AND waitlist_position>0 AND waitlist_position IS NOT NULL)
    OR (status<>'WAITLISTED' AND waitlist_position IS NULL));
ALTER TABLE enrollments ADD CONSTRAINT uq_waitlist_position UNIQUE(section_id,waitlist_position) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE registration_audit ADD FOREIGN KEY(section_id) REFERENCES course_sections(section_id);
ALTER TABLE registration_audit ADD FOREIGN KEY(student_id) REFERENCES students(student_id);
CREATE INDEX idx_audit_section ON registration_audit(section_id,audit_id);
