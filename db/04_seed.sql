-- =========================================================
-- 04_seed.sql
-- Optional catalog data. The registration window lasts 14 days from seeding.
-- =========================================================

INSERT INTO terms (name, registration_opens_at, registration_closes_at)
VALUES ('Fall 2026', now(), now() + interval '14 days');

INSERT INTO courses (course_code, title, credits) VALUES
    ('CS101', 'Introduction to Programming', 4),
    ('CS201', 'Data Structures & Algorithms', 4),
    ('MA110', 'Calculus I', 3),
    ('EC150', 'Principles of Economics', 3);

-- One popular, tightly-capped section: this is the "hot row".
INSERT INTO course_sections (course_id, term_id, section_code, instructor, capacity, waitlist_capacity)
SELECT c.course_id, t.term_id, 'A', 'Dr. Rao', 30, 15
FROM courses c, terms t
WHERE c.course_code = 'CS101' AND t.name = 'Fall 2026';

-- A few other ordinary sections for realism / analytics variety.
INSERT INTO course_sections (course_id, term_id, section_code, instructor, capacity, waitlist_capacity)
SELECT c.course_id, t.term_id, 'A', 'Dr. Iyer', 60, 10
FROM courses c, terms t
WHERE c.course_code = 'CS201' AND t.name = 'Fall 2026';

INSERT INTO course_sections (course_id, term_id, section_code, instructor, capacity, waitlist_capacity)
SELECT c.course_id, t.term_id, 'A', 'Dr. Mehta', 120, 0
FROM courses c, terms t
WHERE c.course_code = 'MA110' AND t.name = 'Fall 2026';

INSERT INTO course_sections (course_id, term_id, section_code, instructor, capacity, waitlist_capacity)
SELECT c.course_id, t.term_id, 'A', 'Dr. Shah', 80, 5
FROM courses c, terms t
WHERE c.course_code = 'EC150' AND t.name = 'Fall 2026';
