# Setup and credentials

Use Python 3.12 and a dedicated nonproduction Supabase project. Use fabricated data only.

## 1. Supabase configuration

1. Create/select your Supabase project and save the database password securely.
2. Under Auth, configure an asymmetric JWT signing key. This backend defaults to ES256; set RS256 instead only if your project actually uses RS256. HS256 is deliberately unsupported.
3. Copy the project URL and publishable key from project settings. The publishable key is used by the backend for password login and refresh. No service-role key is required by the provided bootstrap script.
4. From **Connect**, copy the direct connection string or **session pooler** connection string if the host requires IPv4. Use the database credentials in that string, not the Supabase account password. Percent-encode special characters in the password.
5. Use SQLAlchemy's `postgresql+psycopg://` scheme and append `?sslmode=require`. Do not use the transaction pooler for this initial setup.
6. In Auth's user management, manually create and confirm five demo accounts: citizen, helper, officer, admin and auditor. Save their Auth user UUIDs. Keep passwords outside the repository. Disable public signup if the project is demo-only.

## 2. Configure the shared API

From the repository root, install the backend requirements and configure the root
`.env` using `.env.example`. Set the Supabase URL, publishable key, signing
algorithm, and PostgreSQL connection string for the same project. Use the
Supabase credential for the database owner. Keep the database URL and all
internal, AI, and provider keys on the server.

Set `MOCK_BASE_URL` to the shared FastAPI host and set each of `NADRA_MOCK_KEY`,
`RAAST_MOCK_KEY`, and `SMS_MOCK_KEY`. For Member 2 claim checks and Scam Shield,
set `AI_STUB=false`, point `AI_BASE_URL` to the shared FastAPI host, and set
`INTERNAL_SERVICE_KEY` and `AI_API_KEY` separately. Keep
`AI_DUPLICATES_STRICT=true`. Use `AGENT_MODE=deterministic`.
See [Member 2 integration](AI_INTEGRATION.md) for the environment and manual checks.

Set `CORS_ORIGINS` to a comma-separated list of additional frontend origins.
Set `VITE_API_URL` in the frontend build environment to the shared API URL.
Configure a persistent private volume for `UPLOAD_DIR` when deploying.

## 3. Migrate and seed

Stop the old API and worker and take a database backup before the queue cutover.
From the repository root, with the backend virtual environment activated:

```bash
(cd backend/platform/backend && alembic upgrade head)
(cd backend && python -m app.integrations.mocks.fixtures)
```

The second revision preserves the old processing ledger, queues submitted work
for the new worker, and moves interrupted legacy processing to human review.
The migration is forward only. Restore the backup if a rollback is required.
The database must have the Supabase `anon` and `authenticated` roles.

Copy [demo-accounts.example.json](demo-accounts.example.json) and replace the placeholders with the
existing Supabase Auth UUIDs. Bind the application profiles and seed policy v1:

```bash
(cd backend/platform/backend && python -m app.bootstrap --accounts ../../../docs/demo-accounts.json)
```

This binds existing Auth users without changing their passwords or roles.
The tenant ID in that file must match `DEMO_TENANT_ID` for mock controls.

## 4. Start the shared API and worker

```bash
(cd backend && RUN_JOB_WORKER=true uvicorn main:app --host 127.0.0.1 --port 8000)
```

Enable the worker on exactly one process. Other API processes can use
`RUN_JOB_WORKER=false`. Use `/health` for liveness and `/ready` for database
schema, auth configuration, and heartbeat checks when the worker is enabled.
Members 3 and 4 can use the job and mock control admin APIs with an admin JWT.

For the clean smoke test, file a synthetic claim for Muhammad Ali
(`MOCK-123456`, `MOCK-ACCOUNT-001`) with income under policy and attach
both an identity proof and an income proof as sharp JPEG or PNG images. Use only test files. The optional
synthetic number `+920000000001` exercises the SMS gateway. Confirm it reaches
`cleared`, assign it to an officer, approve it, and wait for one confirmed mock
payment. A case with no synthetic number receives in-app notices.

The previous polling callbacks under `/internal/jobs/{id}/start`,
`/decision`, and `/fail` have been retired. The shared app runs the durable
worker directly. Internal job and agent routes accept `X-Service-Key` and must
be reachable only to trusted services.
