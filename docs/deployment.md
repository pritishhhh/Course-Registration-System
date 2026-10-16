# Deployment

## Stack

Vercel hosts the FastAPI application and static portal. Supabase supplies PostgreSQL and authentication. Registration uses parameterized SQL over the server-only database connection; the browser never writes through Supabase's Data API.

Supabase currently offers a free plan with 500 MB database storage and 50,000 monthly active authentication users. Free projects may pause after a week of inactivity. Check [current limits](https://supabase.com/pricing) before deployment. A university registration surge needs capacity planning beyond a free demonstration environment.

## 1. Create a Supabase project

Choose a region near your Vercel deployment. Record the project URL and **publishable key** from the project's API settings. A legacy `anon` key also works. Do not use a secret or `service_role` key: `/api/config` deliberately exposes the public key and rejects privileged key formats.

From **Connect**, copy the **shared transaction pooler** connection string, usually port `6543`. Copy the actual host; do not construct it from a region name. URL-encode special characters in the password and add `?sslmode=require` if there is no query string.

```text
DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:6543/postgres?sslmode=require
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

Keep the database URL in `.env` locally and Vercel's environment settings in deployment. Never commit it. The application assumes the restricted `registration_app` role inside each transaction and disables driver prepared statements for transaction pooling.

Reference: [Supabase connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 2. Initialize the database

Install `requirements.txt`, put the connection settings in `.env`, then run this once against an **empty application database**:

```sh
python scripts/init_db.py --seed
```

The command installs schema, functions, triggers, security policies, and the example catalog in one transaction. A failure rolls everything back. It refuses to overwrite an existing application schema. Initialization needs an owner account able to create roles and grant membership; the Supabase `postgres` connection is intended for this step.

Alternatively, execute the numbered `db/*.sql` files in order through the Supabase SQL editor, including `05_security.sql` and `06_metadata.sql`. Use the Python command when you want one transaction for the entire setup. `04_seed.sql` is optional; it creates four course sections and a registration window lasting 14 days from installation. Adjust the term dates deliberately after that window closes.

If you already use the original repository schema, take a backup and run `python scripts/upgrade_legacy.py` instead. It normalizes waitlist positions and seat counters, replaces the functions and permissions, and preserves enrollment history. Overbooked sections or a queue with vacant seats cause the upgrade to roll back for an operator decision. Existing students remain unlinked until an administrator assigns their verified `auth_subject`; matching an email never grants ownership automatically.

The tables have RLS enabled. Supabase `anon` and `authenticated` roles receive no application table policies or permission to call the enrollment functions. These functions are private server operations. The `registration_app` role can read the public catalog and only the student registrations selected by the verified server identity. Never grant that role to a browser-facing Supabase role.

## 3. Configure authentication

### GitHub OAuth: free, without an email service

1. Create a GitHub OAuth application in your GitHub developer settings.
2. Copy the callback URL shown by Supabase's GitHub provider settings. Use it as the OAuth application's callback URL.
3. Add the GitHub client ID and secret to Supabase's **Authentication -> Sign In / Providers -> GitHub** settings and enable the provider.
4. Set your deployed application URL as Supabase's **Site URL**, and allow the local URL `http://localhost:8000` as an additional redirect during development.

The portal's **Continue with GitHub** button uses Supabase's standard implicit browser flow. Tokens returned in the URL fragment are removed from the address bar immediately. Credentials remain in the current browser tab's session storage, with refresh-token rotation; they are cleared on sign-out. All API requests verify the access token against Supabase's `/auth/v1/user` endpoint and require a confirmed email.

Reference: [GitHub provider configuration](https://supabase.com/docs/guides/auth/social-login/auth-github).

### Email and password

Enable the Email provider with confirmation required. Sign-up and sign-in are available in the portal. Supabase's default email sender only delivers to pre-authorized organization addresses and has a small hourly quota. For public email sign-ups, configure a custom SMTP provider with a suitable free tier. GitHub OAuth avoids that dependency.

Reference: [Supabase email restrictions and SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

## 4. Import into Vercel

1. Import the GitHub repository. If the app is placed inside a larger repository, select the directory containing `app.py` as the project root.
2. Select **FastAPI**, or let Vercel detect it. Keep the default build and output settings; do not configure a frontend export directory.
3. Add the three environment variables above for the intended environment. Keep preview databases separate from production.
4. Deploy. `app.py` exports the ASGI application. `public/` contains CDN assets, and `vercel.json` adds security headers.
5. Set Supabase's Site URL and allowed redirect URLs to the resulting Vercel origin. Add individual preview origins only when needed.
6. Verify `/api/health`, browse courses, sign in, register, and withdraw. Confirm that a second account cannot see the first account's registrations.

Vercel installs the Python dependencies; Docker is for local development only. Schema changes are an explicit operator step, never an import-time side effect or build command. The API opens and closes one connection per transaction and relies on Supabase's external pooler. A cold start does not lose data or create a separate registration queue.

Reference: [FastAPI deployment on Vercel](https://vercel.com/docs/frameworks/backend/fastapi).

## Endpoint reference

| Method | Path | Authentication |
| --- | --- | --- |
| GET | `/api/health` | Public; checks database access |
| GET | `/api/config` | Public; publishable authentication settings only |
| GET | `/api/sections` | Public catalog and aggregate availability |
| GET | `/api/me/enrollments` | Bearer token; active registrations for the caller |
| POST | `/api/sections/{id}/register` | Bearer token; registers the caller |
| DELETE | `/api/sections/{id}/registration` | Bearer token; drops the caller's registration |

Expected conflicts return `409`, missing sections return `404`, invalid identities return `401`/`403`, and unavailable dependencies or lock timeouts return `503`. Registration and withdrawal retries are idempotent for the current active registration. Do not automatically retry a timed-out withdrawal after the user has re-registered, because it may refer to a new enrollment.

## Operations

- Catalog administration uses controlled SQL; there is no public administrator endpoint.
- Keep transactions short. Do not run the load generator against the deployed application database.
- Monitor database connections, lock wait time, function errors, and storage growth. Audit records accumulate and need an explicit archival policy for long-running deployments.
- Set Vercel firewall/rate-limit rules and Supabase authentication abuse controls appropriate to public traffic. The application does not implement a distributed request limiter.
- A full institutional rollout also needs approved student identities, registrar permissions, enrollment policies, backups, and operational monitoring. Public OAuth sign-up is appropriate for a demonstration, not proof of university membership.
