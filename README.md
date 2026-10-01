# Concurrent Course Registration System

A Django student website backed by PostgreSQL seat allocation functions. Students can create an account, browse sections, register, see their enrollments or waitlist positions, and drop a section. Staff can manage courses, terms, and sections through Django admin. The database serializes competing requests for a section with `SELECT ... FOR UPDATE`, so multiple web workers share the same seat decision.

This is a functional pilot, not yet a university production system. The limitations below matter before using real student data.

## Run locally

1. Start the disposable database: `docker compose up -d`. Compose loads `db/01_schema.sql` through `db/04_seed.sql` only when its data volume is first created.
2. Install dependencies: `python -m pip install -r requirements.txt -r scripts/requirements.txt`.
3. Set `DEBUG=1` and `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/registration` in your shell.
4. Run `python manage.py migrate`, then `python manage.py runserver`.
5. Open `http://localhost:8000/`. Sign up for a student account. To use the staff area, run `python manage.py createsuperuser` and open `/admin/`.

Run `python scripts/verify_registration.py` only against a disposable database: it resets the sample `CS101-A` section. `python scripts/verify_web.py` creates a test student and exercises the main website flow. GitHub Actions runs both checks against a fresh PostgreSQL service on every push and pull request.

The sample SQL files are not automatically reloaded when an existing Compose volume starts again. Do not delete a database volume containing data just to apply a schema change; use a new migration.

## Render deployment preparation

`render.yaml` declares one Python web service and one private Render PostgreSQL instance. The web service gets `DATABASE_URL` from the database and a generated `SECRET_KEY`. It installs dependencies, collects admin static files, applies the initial SQL schema, runs Django migrations, and starts Gunicorn. The database has no public IP allowlist entries. Render is configured to deploy commits after GitHub checks pass.

To put this online, push the reviewed changes to GitHub, connect the repository to a Render Blueprint, and review the resource plan before creation because it can incur charges. After the first deployment, run `python manage.py seed_demo` in the Render shell to add four sample courses, then create a staff account with `python manage.py createsuperuser`. The seed command can be rerun without duplicating its catalog. The production deployment does **not** load `db/04_seed.sql` or any fake students.

The schema runner records hashes of applied SQL files and refuses to silently replay a changed file. Add a new numbered migration for later database changes. It is intended for a fresh production database; the existing Compose database was initialized directly by Docker and is not registered with this migration runner.

## Registration behavior

- `fn_register_safe(student_id, section_id)` locks the student and section rows in a consistent order, checks the registration window and existing active enrollment, then allocates a seat or a waitlist place in one transaction. A student can hold only one active section of a course per term.
- `fn_drop_enrollment(student_id, section_id)` uses the same lock order, then drops a seat and promotes the first waitlisted student while holding the section lock.
- Unique and check constraints prevent duplicate active enrollments, invalid waitlist positions, and seat counters beyond capacity.
- A row lock prevents overbooking for callers that use these functions. It does not guarantee that requests are served in exact HTTP arrival order.

The old load-test example claiming 75 persisted enrollments for a 30-seat section conflicted with the schema's capacity check. The deliberately unsafe comparison path may instead produce database errors. The CI verification script asserts invariants; the comparison script is educational only.

## Work still needed before real student use

1. Verify email addresses or integrate the institution's identity provider; self-signup currently trusts the submitted email.
2. Add prerequisite, schedule-clash, credit-limit, academic-hold, and drop-deadline rules. Seat availability and one active section per course are the only eligibility rules currently enforced.
3. Restrict the application's database role to approved operations. The initial Render database owner can still alter tables directly.
4. Add request idempotency keys, throttling, lock timeouts, and controlled retries for transient errors. Define p95/p99 latency and run realistic burst tests against the deployed service.
5. Add password-reset email, account recovery, user support, backup and restore drills, audit access controls and retention, monitoring, and incident procedures.
6. Add a proper sequence of SQL migrations for future releases. Do not edit already-applied schema files.

For very large opening-day bursts, use admission control or a waiting room so database connection and lock queues remain bounded. Scale web workers based on measured traffic while keeping seat allocation in PostgreSQL.
