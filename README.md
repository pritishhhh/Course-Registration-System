# Concurrent Course Registration System

This project demonstrates how to handle extreme database concurrency—specifically, solving the race condition that occurs when hundreds of users attempt to book the final available seats simultaneously (e.g., concert tickets, university courses).

It showcases the difference between a naive check-then-act pattern and a robust implementation using PostgreSQL row-level pessimistic locking (`SELECT ... FOR UPDATE`), proving that the latter prevents overbooking under intense load.

## The Problem

Section `CS101-A` has 30 seats. At 9:00 AM, 200 students click "Register" at the exact same moment. 

If the application reads the seat count, sees availability, and then writes the enrollment (naive approach), multiple transactions will read the same stale data before any writes land. The result is overbooking.

This project solves the race condition entirely within the database layer using transactions and locking.

## Architecture

- **`course_sections`**: Stores `capacity` and `seats_filled`. Protected by a `CHECK` constraint.
- **`enrollments`**: Enforces a partial unique index so students cannot double-book the same section.
- **`registration_audit`**: An append-only log populated automatically by a trigger to reconstruct the timeline of concurrent requests.

## Concurrency Strategies

| Approach | Mechanism | Trade-offs |
|---|---|---|
| **Pessimistic Locking** (Default) | `SELECT ... FOR UPDATE` locks the row before reading or writing. Concurrent callers queue on the database lock. | Extremely safe, prevents race conditions. Throughput is limited by the lock queue. |
| **Optimistic Locking** | Reads a `version` column and updates only if the version matches. Requires application-side retry logic. | Better throughput under low contention, but can lead to livelock under extreme load. |
| **Naive Check-Then-Act** | Reads seat count and acts. | Included in the load test specifically to demonstrate catastrophic overbooking under concurrency. |

## Running the Load Test

1. Start the PostgreSQL instance and load the schema:
```bash
docker compose up -d
```

2. Install dependencies:
```bash
cd scripts
pip install -r requirements.txt
```

3. Run the load test to see the race condition in action:
```bash
python concurrency_test.py
```
*(You can also run `concurrency_test_multi.py` to test registrations distributed across multiple courses).*

4. Run the analytics query to inspect the waitlist ordering:
```bash
psql postgresql://postgres:postgres@localhost:5432/registration -f ../queries/analytics.sql
```

## Load Test Results

When 200 students race for 30 seats across 50 concurrent workers:

**Naive Approach:**
```
  actual ENROLLED rows in enrollments table: 75
  *** OVERBOOKED by 45 seat(s) ***
```

**Safe Approach (Pessimistic Locking):**
```
  actual ENROLLED rows in enrollments table: 30
  No overbooking.
```

The database forces the concurrent transactions to serialize precisely, ensuring the capacity limits are perfectly respected and waitlists are generated in a strict first-come, first-served order.
