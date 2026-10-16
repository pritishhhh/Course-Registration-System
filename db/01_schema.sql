CREATE TABLE students (
    student_id SERIAL PRIMARY KEY,
    auth_subject UUID UNIQUE,
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) BETWEEN 1 AND 200),
    email TEXT UNIQUE NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE courses (
    course_id SERIAL PRIMARY KEY,
    course_code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    credits SMALLINT NOT NULL DEFAULT 3 CHECK (credits > 0)
);
CREATE TABLE terms (
    term_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    registration_opens_at TIMESTAMPTZ,
    registration_closes_at TIMESTAMPTZ,
    CHECK (registration_closes_at > registration_opens_at)
);
CREATE TABLE course_sections (
    section_id SERIAL PRIMARY KEY,
    course_id INT NOT NULL REFERENCES courses(course_id),
    term_id INT NOT NULL REFERENCES terms(term_id),
    section_code TEXT NOT NULL,
    instructor TEXT,
    capacity INT NOT NULL CHECK (capacity > 0),
    seats_filled INT NOT NULL DEFAULT 0 CHECK (seats_filled >= 0),
    waitlist_capacity INT NOT NULL DEFAULT 10 CHECK (waitlist_capacity >= 0),
    UNIQUE (course_id, term_id, section_code),
    CONSTRAINT seats_within_capacity CHECK (seats_filled <= capacity)
);
CREATE TYPE enrollment_status AS ENUM ('ENROLLED', 'WAITLISTED', 'DROPPED', 'CANCELLED');
CREATE TABLE enrollments (
    enrollment_id BIGSERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(student_id),
    section_id INT NOT NULL REFERENCES course_sections(section_id),
    status enrollment_status NOT NULL,
    waitlist_position INT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((status = 'WAITLISTED' AND waitlist_position > 0 AND waitlist_position IS NOT NULL)
        OR (status <> 'WAITLISTED' AND waitlist_position IS NULL)),
    -- Deferred because closing a gap may temporarily collide with a later row.
    CONSTRAINT uq_waitlist_position UNIQUE (section_id, waitlist_position)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX uq_active_enrollment ON enrollments (student_id, section_id)
    WHERE status IN ('ENROLLED', 'WAITLISTED');
CREATE INDEX idx_enrollments_section_status ON enrollments (section_id, status);
CREATE INDEX idx_enrollments_student ON enrollments (student_id);
CREATE TABLE registration_audit (
    audit_id BIGSERIAL PRIMARY KEY,
    section_id INT NOT NULL REFERENCES course_sections(section_id),
    student_id INT REFERENCES students(student_id),
    action TEXT NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_audit_section ON registration_audit (section_id, audit_id);
