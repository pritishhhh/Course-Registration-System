-- Section demand and counter reconciliation. A difference should always be zero.
SELECT s.section_id, c.course_code, s.section_code, s.capacity, s.seats_filled,
       count(e.enrollment_id) FILTER (WHERE e.status='ENROLLED') AS actual_enrolled,
       s.seats_filled-count(e.enrollment_id) FILTER (WHERE e.status='ENROLLED') AS counter_difference,
       count(e.enrollment_id) FILTER (WHERE e.status='WAITLISTED') AS waitlisted,
       round(100.0*s.seats_filled/s.capacity,1) AS fill_percent
FROM course_sections s JOIN courses c USING(course_id)
LEFT JOIN enrollments e USING(section_id)
GROUP BY s.section_id,c.course_code
ORDER BY s.section_id;

-- Successful transitions and full rejections, not HTTP request throughput.
SELECT date_trunc('second',created_at) AS second,
       count(*) FILTER (WHERE action='ENROLLED') AS enrolled,
       count(*) FILTER (WHERE action='WAITLISTED') AS waitlisted,
       count(*) FILTER (WHERE action='PROMOTED_FROM_WAITLIST') AS promoted,
       count(*) FILTER (WHERE action='REJECTED_FULL') AS rejected
FROM registration_audit GROUP BY 1 ORDER BY 1;

-- Queue order follows the persisted position, not browser-click timestamps.
SELECT section_id,student_id,waitlist_position AS stored_position,
       row_number() OVER (PARTITION BY section_id ORDER BY waitlist_position,enrollment_id) AS computed_position
FROM enrollments WHERE status='WAITLISTED'
ORDER BY section_id,stored_position;

-- Integrity check: the active-enrollment unique index should make this empty.
SELECT student_id,section_id,count(*) AS active_rows
FROM enrollments WHERE status IN ('ENROLLED','WAITLISTED')
GROUP BY student_id,section_id HAVING count(*)>1;

-- Audit sequence numbers reflect insertion order, not a global commit order.
SELECT audit_id,created_at,student_id,action,detail FROM registration_audit
WHERE section_id=(SELECT min(section_id) FROM course_sections)
ORDER BY audit_id LIMIT 50;
