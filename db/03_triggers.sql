-- Exactly one event per status transition; renumbering is not a request.
CREATE FUNCTION trg_enrollment_audit() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE event TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN event := NEW.status::TEXT;
    ELSIF NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NEW;
    ELSIF OLD.status = 'WAITLISTED' AND NEW.status = 'ENROLLED' THEN event := 'PROMOTED_FROM_WAITLIST';
    ELSE event := 'DROPPED_' || OLD.status::TEXT;
    END IF;
    INSERT INTO registration_audit (section_id, student_id, action, detail)
    VALUES (NEW.section_id, NEW.student_id, event,
        jsonb_build_object('enrollment_id', NEW.enrollment_id, 'position', NEW.waitlist_position));
    RETURN NEW;
END;
$$;
CREATE TRIGGER enrollment_audit AFTER INSERT OR UPDATE ON enrollments
FOR EACH ROW EXECUTE FUNCTION trg_enrollment_audit();
CREATE FUNCTION trg_audit_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'registration_audit is append-only'; END;
$$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON registration_audit
FOR EACH ROW EXECUTE FUNCTION trg_audit_immutable();
-- Validate final state, including unsupported direct writes by administrators.
CREATE FUNCTION trg_section_invariants() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    sid INT;
    sec course_sections%ROWTYPE;
    enrolled INT;
    waiting INT;
    max_position INT;
BEGIN
    IF TG_TABLE_NAME = 'enrollments' AND TG_OP = 'UPDATE' THEN
        IF OLD.section_id <> NEW.section_id OR OLD.student_id <> NEW.student_id THEN
            RAISE EXCEPTION 'Enrollment identity is immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN sid := OLD.section_id; ELSE sid := NEW.section_id; END IF;
    SELECT * INTO sec FROM course_sections WHERE section_id = sid FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT count(*) FILTER (WHERE status = 'ENROLLED'),
           count(*) FILTER (WHERE status = 'WAITLISTED'),
           max(waitlist_position) FILTER (WHERE status = 'WAITLISTED')
    INTO enrolled, waiting, max_position FROM enrollments WHERE section_id = sid;
    IF enrolled <> sec.seats_filled OR waiting > sec.waitlist_capacity
        OR (waiting > 0 AND max_position <> waiting)
        OR (waiting > 0 AND enrolled < sec.capacity) THEN
        RAISE EXCEPTION 'Section % invariant violation', sid USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER enrollment_invariants AFTER INSERT OR UPDATE OR DELETE ON enrollments
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_section_invariants();
CREATE CONSTRAINT TRIGGER section_invariants AFTER INSERT OR UPDATE ON course_sections
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_section_invariants();
