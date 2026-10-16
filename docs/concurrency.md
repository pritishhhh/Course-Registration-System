# Concurrency and validation

## Transaction model

`fn_register_safe` locks the section with `SELECT ... FOR UPDATE`, checks for an existing active enrollment, checks the registration window, and either takes a seat or appends a waitlist entry. The section lock remains held until the API commits. A competing registration for the same section must wait; different sections can progress independently.

`fn_drop_enrollment` uses the same section-first lock order. An enrolled withdrawal either promotes the earliest persisted waitlist entry without changing the filled count, or decrements the count when there is no queue. A waitlist withdrawal only moves entries behind the departing student.

Constraints enforce valid queue positions, unique positions per section, and a single active registration per student and section. Deferred triggers reconcile the final seat count against actual enrollment rows, check the waitlist bound and contiguous positions, and reject a nonempty waitlist with vacant seats. The API commits before returning success, so deferred failures cannot be reported as successful registrations.

These guarantees require ordinary PostgreSQL transactions and enabled constraints/triggers. Administrators can bypass safeguards by disabling triggers or truncating tables; the application role cannot do that. The default `READ COMMITTED` isolation level is used. A caller using higher isolation levels must retry serialization failures as a whole transaction.

Lock acquisition does not guarantee strict browser-click FIFO. Persisted waitlist order determines promotion. Do not use `SKIP LOCKED` for seat allocation: skipping the only section row would give misleading availability. Multi-section operations are not supported atomically; any future batch operation must lock sections in ascending ID order and account for deadlock retries.

## Run regressions

Use a dedicated PostgreSQL database ending in `_test`. Initialize it with `scripts/init_db.py`, using `DATABASE_URL` for that setup step only. Then set `TEST_DATABASE_URL` for the tests. The suite truncates application data in this database between cases, so keep it disposable.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Without `TEST_DATABASE_URL`, database-dependent tests skip explicitly; API validation and authentication failure tests still run. CI supplies a disposable PostgreSQL instance and runs the full suite.

Coverage includes concurrent capacity competition, repeated requests, middle/head/tail queue departures, concurrent promotions, registration windows, transaction rollback, counter drift, direct-write rejection, runtime role permissions, private student records, forged identities, and privileged-key disclosure prevention.

## Threaded benchmark

```sh
python scripts/concurrency_test.py
python scripts/concurrency_test_multi.py
```

Both commands use `TEST_DATABASE_URL` and reset test data. Workers create their own connection and close it on every outcome, including errors. Exceptions propagate and correctness assertions fail the process. No global connection pool is created during module import.

| Variable | Default | Accepted range |
| --- | --- | --- |
| `NUM_STUDENTS_TO_TRY` | 200 | 1-20000 |
| `NUM_THREADS` | 20 | 1-80 |
| `NUM_SUBJECTS` | 4 | 1-4 |
| `SUBJECT_CAPACITY` | 30 | 1-20000 |
| `NUM_COURSES_PER_STUDENT` | 2 | 1-4, capped to available subjects |

Targets are deterministic for a given configuration. The benchmark checks exact enrolled counts, waitlist bounds, and contiguous queue positions, rather than only comparing the counter to capacity. This measures a local database/client workload; it is not a Vercel throughput guarantee.

## Unsafe comparison

```sh
python scripts/naive_demo.py
```

This optional demonstration creates separate `benchmark_naive` tables in the disposable test database. Twenty threads read one available seat, synchronize, and then independently insert enrollments. The resulting overbooking illustrates check-then-act without disabling or corrupting the production constraints. It is never exposed by the API.

## Legacy schema

Back up first, stop writers, and run `python scripts/upgrade_legacy.py` with the original database URL. The upgrade takes exclusive table locks and applies its changes in one transaction. It rejects overbooked or otherwise inconsistent data that would require deciding which student should keep a seat. Old audit records are retained; reports should account for the original revision's duplicate audit events when analyzing historical data.
