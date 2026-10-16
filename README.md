# Course Registration System

A PostgreSQL-backed course registration application with a FastAPI service, a responsive student portal, and Supabase authentication. Designed for deployment on Vercel.

Students can browse available sections, register for courses, join a bounded waitlist, and withdraw. Dropping an enrolled course automatically promotes the next waitlisted student in the same transaction.

## Features

- Database transactions and section-level row locks prevent overbooking.
- Unique active enrollments make repeated registration requests idempotent.
- Ordered waitlists with atomic promotion and consistent queue positions.
- Registration windows enforced by the database.
- Verified Supabase identities and private student registration records.
- Database invariants, append-only audit events, and automated concurrency tests.

## Architecture

```text
Browser -> Vercel / FastAPI -> Supabase PostgreSQL
       -> Supabase Auth          transactions + row locks
```

The browser authenticates with Supabase and sends its access token to the API. The server verifies the token before resolving the student identity. All enrollment decisions happen in PostgreSQL; no application thread or Vercel instance owns registration state.

## Quick start

Requires Python 3.12+, Docker, and a Supabase project for authentication.

```sh
python -m venv .venv
# Activate .venv using the command for your shell.
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and enter your Supabase URL and publishable key. The default database URL connects to local PostgreSQL.

```sh
docker compose up -d --wait
python -m uvicorn app:app --reload
```

Open [localhost:8000](http://localhost:8000). Interactive API documentation is available at `/docs`. Docker initializes the database and example catalog on its first run. Authentication setup is covered in the [deployment guide](docs/deployment.md).

## Deploy on Vercel

Use **Supabase Free** for PostgreSQL and authentication, and deploy this repository as a **FastAPI** project on Vercel. No paid course-data or AI API is required.

Set `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_PUBLISHABLE_KEY` in Vercel, initialize the Supabase database, and configure your authentication redirect URLs. Follow the [deployment guide](docs/deployment.md) for the complete setup and free-plan limitations.

## Validation

Install `requirements-dev.txt`, initialize a disposable PostgreSQL database whose name ends in `_test`, and set `TEST_DATABASE_URL` to its connection URL.

```sh
python -m pytest -q
python scripts/concurrency_test_multi.py
```

Database tests and benchmarks reset their test data. They never fall back to `DATABASE_URL`. GitHub Actions runs the API tests, database regressions, and a threaded benchmark on an isolated PostgreSQL service.

See [concurrency and testing](docs/concurrency.md) for configuration and the isolated unsafe comparison, and the [technical review](docs/review.md) for the defects addressed in this revision.

## Project structure

| Directory | Purpose |
| --- | --- |
| `db/` | Schema, transaction functions, audit triggers, and access policies |
| `server/` | Authentication and database connection handling |
| `public/` | Student portal |
| `scripts/` | Database setup, legacy upgrade, and load testing |
| `tests/` | API, integrity, authorization, and concurrency regressions |
| `queries/` | Operational reporting |

This is a registration reference application. Institution-specific rules such as prerequisites, timetable conflicts, credit limits, and registrar administration are outside its current scope.
