# Technical review

The original repository was a database concurrency demonstration rather than a deployable service. This revision preserves PostgreSQL as the authority for allocation and adds a serverless API and authenticated student portal.

## Defects addressed

| Area | Original behavior | Resolution |
| --- | --- | --- |
| Waitlist withdrawal | Decremented every remaining position, including people ahead of the departing student; position zero and collisions were possible. | Shift only positions behind the departure. |
| Queue integrity | No positive-position, status/position, or unique-position constraints. | Add shape checks, deferred uniqueness, and final-state reconciliation. |
| Seat integrity | The counter's capacity check did not guarantee actual enrollment rows matched the counter. | Reconcile committed rows and counters with deferred triggers. |
| Duplicate retries | A previously enrolled student could receive a full-section rejection when both queues were full. | Resolve existing active status before capacity and registration-window decisions. |
| Registration windows | Open and close dates were unused. | Enforce them after acquiring locks with the current wall clock. |
| Missing student | An invalid student raised a foreign-key error. | Return an explicit database result; the public API derives identities from verified auth. |
| Promotion identifier | A `BIGSERIAL` enrollment ID was stored in an `INT` variable. | Use `BIGINT`. |
| Audit semantics | Trigger and procedure inserted two events for one successful registration; analytics treated these as repeat attempts. | One transition event, with separate reporting for transitions and rejected attempts. |
| Audit integrity | Append-only was a comment; any writable client could edit/delete history. | Immutable-update/delete trigger, foreign keys, RLS, and restricted permissions. |
| Naive baseline | Autocommit inserted enrollment rows before a separate counter update that could fail, leaving inconsistent production data. | Use isolated unconstrained demo tables only. |
| Pooled transactions | Autocommit settings leaked between test phases; failed transactions could return to the pool without rollback. | Remove the shared pool and use explicit per-task connection contexts. |
| Connection lifecycle | psycopg2 connection contexts committed/rolled back but did not close helper connections. | psycopg3 contexts commit/roll back and close deterministically. |
| Import side effects | Importing the multi-course script immediately opened a database pool. | No database I/O at import. |
| Test reliability | Exceptions became printed counters; no integrity assertions or failing exit status. | Propagate worker exceptions and assert actual rows, counts, and queue order. |
| Test data | Global resets, count-based synthetic email generation, ambiguous section selection, and capacity updates before cleanup. | Disposable test URL, validated database suffix, deterministic fixtures and targets, reset before setup. |
| CI | Manual-only workflow, initialization without fail-fast SQL, and no database regression suite. | Push/PR/manual validation, atomic initialization, assertions, bounded job timeout, and read-only workflow permissions. |
| Optimistic variant | Inconsistent full/duplicate/waitlist behavior, missing window enforcement and audit parity, and incomplete caller retry handling. | Remove the unused production variant and version column; expose one supported allocation path. |
| Deployment | No HTTP application, dependency manifest at root, auth, or Vercel entry point. | FastAPI app, static portal, runtime dependencies, public/private routes, and Vercel configuration. |
| Authorization | No verified mapping between a web identity and student records. | Verify Supabase tokens and resolve students by immutable auth subject; ignore caller-supplied student IDs. |
| Data API exposure | Database functions had PostgreSQL's default PUBLIC execute permissions; Supabase defaults could expose them as RPC. | Revoke public/browser-role access, enable RLS, pin security-definer search paths, and use a restricted server role. |
| Serverless state | No connection or lock strategy for multiple function instances. | External transaction pooler, per-request connections, no shared transaction state, bounded statement/lock/connect timeouts. |
| Secret handling | No distinction between browser and server credentials. | Expose only validated publishable/anon key formats; keep database credentials server-only and ignore local secrets. |
| SQL reporting | Timestamp order differed from queue order; audit duplicates inflated attempt counts. | Report persisted queue order, counter reconciliation, and clearly labeled transition counts. |
| Documentation | Unverified benchmark examples and strict first-come-first-served claims. | Replace with product, setup, operational boundaries, and reproducible tests. |

## Limits and deliberate scope

The application is suitable as a deployment-ready reference and public demonstration after account configuration. It does not claim to be a complete university registration platform. Institution membership, prerequisites, credit caps, timetable conflicts, registrar roles, and administrative workflows require explicit business rules.

The database checks are correctness safeguards, not a guarantee of unlimited throughput. A popular section serializes allocations and performs queue/counter reconciliation; long histories and high contention need profiling. Requests fail with `503` rather than hold locks indefinitely, and clients should refresh state before retrying uncertain outcomes.

Authentication is checked against Supabase on protected requests, adding a network round trip while avoiding unverified token claims. Browser sessions are scoped to a tab. Public endpoints need deployment-level traffic controls; audit history needs a retention/archival plan. Free hosted services have quotas and availability limits.
