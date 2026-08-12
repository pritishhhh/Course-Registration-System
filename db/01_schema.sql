-- =========================================================
-- 01_schema.sql
-- Core schema for the Concurrent Course Registration System
-- =========================================================

CREATE TABLE students (
    student_id   SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE courses (
    course_id    SERIAL PRIMARY KEY,
    course_code  TEXT UNIQUE NOT NULL,
    title        TEXT NOT NULL,
    credits      SMALLINT NOT NULL DEFAULT 3
);

CREATE TABLE terms (
    term_id                  SERIAL PRIMARY KEY,
    name                     TEXT NOT NULL,
    registration_opens_at    TIMESTAMPTZ,
    registration_closes_at   TIMESTAMPTZ
);

-- The "hot row" of the whole system: capacity + seats_filled on a section
-- is what every concurrent request is racing to update safely.
CREATE TABLE course_sections (
    section_id        SERIAL PRIMARY KEY,
    course_id         INT NOT NULL REFERENCES courses(course_id),
    term_id           INT NOT NULL REFERENCES terms(term_id),
    section_code      TEXT NOT NULL,
    instructor        TEXT,
    capacity          INT NOT NULL CHECK (capacity > 0),
    seats_filled      INT NOT NULL DEFAULT 0 CHECK (seats_filled >= 0),
    waitlist_capacity INT NOT NULL DEFAULT 10,
    version           INT NOT NULL DEFAULT 0,  -- used by the optimistic-locking variant, see README
    UNIQUE (course_id, term_id, section_code),
    CONSTRAINT seats_within_capacity CHECK (seats_filled <= capacity)
);

CREATE TYPE enrollment_status AS ENUM ('ENROLLED', 'WAITLISTED', 'DROPPED', 'CANCELLED');

CREATE TABLE enrollments (
    enrollment_id     BIGSERIAL PRIMARY KEY,
    student_id        INT NOT NULL REFERENCES students(student_id),
    section_id        INT NOT NULL REFERENCES course_sections(section_id),
    status            enrollment_status NOT NULL,
    waitlist_position INT,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    decided_at        TIMESTAMPTZ
);

-- A student can only hold ONE *active* (enrolled/waitlisted) row per section.
-- Partial unique index (not a table constraint) so a student CAN re-register
-- after dropping -- old DROPPED/CANCELLED rows don't block a new attempt.
CREATE UNIQUE INDEX uq_active_enrollment
    ON enrollments (student_id, section_id)
    WHERE status IN ('ENROLLED', 'WAITLISTED');

CREATE INDEX idx_enrollments_section_status ON enrollments (section_id, status);
CREATE INDEX idx_enrollments_student ON enrollments (student_id);
CREATE INDEX idx_enrollments_waitlist_order ON enrollments (section_id, waitlist_position)
    WHERE status = 'WAITLISTED';

-- Append-only audit trail. Useful both for debugging races and for showing
-- you understand that "what happened, in what order" matters as much as
-- "what is the current state" in a high-contention system.
CREATE TABLE registration_audit (
    audit_id    BIGSERIAL PRIMARY KEY,
    section_id  INT NOT NULL,
    student_id  INT,
    action      TEXT NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
