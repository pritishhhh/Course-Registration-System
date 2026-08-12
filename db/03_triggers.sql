-- =========================================================
-- 03_triggers.sql
-- A lightweight trigger that mirrors every enrollment status change into
-- the audit log automatically -- a safety net even if someone bypasses
-- the stored procedures and updates enrollments directly.
-- =========================================================

CREATE OR REPLACE FUNCTION trg_enrollment_audit() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO registration_audit (section_id, student_id, action, detail)
        VALUES (NEW.section_id, NEW.student_id, 'ROW_INSERTED',
                jsonb_build_object('status', NEW.status));
    ELSIF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO registration_audit (section_id, student_id, action, detail)
        VALUES (NEW.section_id, NEW.student_id, 'STATUS_CHANGED',
                jsonb_build_object('from', OLD.status, 'to', NEW.status));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enrollment_audit ON enrollments;
CREATE TRIGGER enrollment_audit
    AFTER INSERT OR UPDATE ON enrollments
    FOR EACH ROW EXECUTE FUNCTION trg_enrollment_audit();

-- Belt-and-suspenders: capacity is already enforced by fn_register_safe's
-- row lock, but this trigger guarantees the invariant at the DB level even
-- if a bug ever lets seats_filled be set directly.
CREATE OR REPLACE FUNCTION trg_check_capacity() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.seats_filled > NEW.capacity THEN
        RAISE EXCEPTION 'seats_filled (%) cannot exceed capacity (%) for section %',
            NEW.seats_filled, NEW.capacity, NEW.section_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS section_capacity_guard ON course_sections;
CREATE TRIGGER section_capacity_guard
    BEFORE UPDATE ON course_sections
    FOR EACH ROW EXECUTE FUNCTION trg_check_capacity();
