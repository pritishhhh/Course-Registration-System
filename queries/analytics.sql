-- =========================================================
-- analytics.sql
-- Run these after concurrency_test.py to explore the resulting data.
-- These are the kind of queries that show range beyond CRUD: window
-- functions, CTEs, ranking, and time-based aggregation.
-- =========================================================

-- 1. Fill rate and waitlist demand per section, ranked by demand.
WITH demand AS (
    SELECT
        s.section_id,
        c.course_code,
        s.section_code,
        s.capacity,
        s.seats_filled,
        count(e.enrollment_id) FILTER (WHERE e.status = 'WAITLISTED') AS waitlisted
    FROM course_sections s
    JOIN courses c ON c.course_id = s.course_id
    LEFT JOIN enrollments e ON e.section_id = s.section_id
    GROUP BY s.section_id, c.course_code, s.section_code, s.capacity, s.seats_filled
)
SELECT
    course_code,
    section_code,
    capacity,
    seats_filled,
    ROUND(100.0 * seats_filled / capacity, 1) AS fill_pct,
    waitlisted,
    RANK() OVER (ORDER BY waitlisted DESC, seats_filled DESC) AS demand_rank
FROM demand
ORDER BY demand_rank;


-- 2. Registration attempts over time (per-second throughput during the
--    concurrency test) -- useful for eyeballing how the system behaved
--    under the burst of simultaneous requests.
SELECT
    date_trunc('second', created_at) AS second,
    count(*) FILTER (WHERE action = 'ENROLLED')  AS enrolled,
    count(*) FILTER (WHERE action = 'WAITLISTED') AS waitlisted,
    count(*) FILTER (WHERE action = 'REJECTED_FULL') AS rejected
FROM registration_audit
GROUP BY 1
ORDER BY 1;


-- 3. For each waitlisted student, how many people are ahead of them and
--    what their live queue position is (recomputed defensively with a
--    window function rather than trusted purely from the stored column).
SELECT
    e.section_id,
    e.student_id,
    e.waitlist_position AS stored_position,
    ROW_NUMBER() OVER (PARTITION BY e.section_id ORDER BY e.requested_at) AS computed_position
FROM enrollments e
WHERE e.status = 'WAITLISTED'
ORDER BY e.section_id, computed_position;


-- 4. Students who tried to register more than once for the same section
--    within the burst (interesting to see how ON CONFLICT / unique index
--    handled duplicate/rapid attempts).
SELECT student_id, section_id, count(*) AS attempts
FROM registration_audit
WHERE action IN ('ENROLLED', 'WAITLISTED', 'ROW_INSERTED')
GROUP BY student_id, section_id
HAVING count(*) > 1
ORDER BY attempts DESC;


-- 5. Simple "audit timeline" for one section -- what happened, in order.
-- Replace :section_id, e.g. SELECT section_id FROM course_sections WHERE section_code='A' LIMIT 1
SELECT created_at, student_id, action, detail
FROM registration_audit
WHERE section_id = (SELECT section_id FROM course_sections LIMIT 1)
ORDER BY created_at
LIMIT 50;
