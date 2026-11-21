# Setup and credentials

This guide contains commands for you to execute later. None were run during implementation. Use Python 3.12 and a dedicated nonproduction Supabase project. Use fabricated data only.

## 1. Supabase configuration

1. Create/select your Supabase project and save the database password securely.
2. Under Auth, configure an asymmetric JWT signing key. This backend defaults to ES256; set RS256 instead only if your project actually uses RS256. HS256 is deliberately unsupported.
3. Copy the project URL and publishable key from project settings. The publishable key is used by the backend for password login and refresh. No service-role key is required by the provided bootstrap script.
4. From **Connect**, copy the direct connection string or **session pooler** connection string if the host requires IPv4. Use the database credentials in that string, not the Supabase account password. Percent-encode special characters in the password.
5. Use SQLAlchemy's `postgresql+psycopg://` scheme and append `?sslmode=require`. Do not use the transaction pooler for this initial setup.
6. In Auth's user management, manually create and confirm five demo accounts: citizen, helper, officer, admin and auditor. Save their Auth user UUIDs. Keep passwords outside the repository. Disable public signup if the project is demo-only.

## 2. Local installation

From the repository root:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Populate `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ALGORITHM=ES256
CORS_ORIGINS=["http://localhost:5173"]
INTERNAL_API_KEY=GENERATE_A_LONG_RANDOM_SERVER_ONLY_SECRET
AI_BASE_URL=
AI_API_KEY=
UPLOAD_DIR=uploads
```

Use the exact host/user/port Supabase provides; the connection string above is illustrative. Generate a service secret with a password manager or `openssl rand -hex 32`. Never expose the database URL, internal key, AI key, or tokens in frontend configuration or source control.

`AI_BASE_URL` is the root URL of Member 2's service, without `/internal/ai`; the backend appends `/internal/ai/scam-check`. `AI_API_KEY` must match that service's accepted `X-API-Key`. Leave both blank until the service exists; scam checks then return 503 rather than invented results. No OpenAI credential is needed by Member 1.

## 3. Apply the schema deliberately

Review the initial migration, then run against the intended nonproduction Supabase project:

```bash
alembic upgrade head
```

Run migrations using the database owner from Supabase. The migration enables RLS and revokes `anon` and `authenticated` table privileges. FastAPI uses the owner connection and must enforce all application authorization itself. The browser must not query these tables directly.

The first migration uses the current SQLAlchemy metadata. Freeze its table definitions before adding subsequent migrations; later model edits must not silently change the meaning of revision 0001.

## 4. Bind the demo users

Copy `docs/demo-accounts.example.json` to a local file. Replace every placeholder with the corresponding existing Supabase Auth UUID. Keep all five users under one synthetic tenant UUID. From `backend`:

```bash
python -m app.bootstrap --accounts /absolute/path/to/demo-accounts.json
```

This inserts application profiles, one citizen profile, and synthetic policy version 1. It does not create Supabase Auth accounts, set passwords, or alter existing roles. To demonstrate helper switching, create a second citizen Auth account and include it in the JSON before running bootstrap again.

## 5. Run the API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/docs`. Login through `/api/v1/auth/login`, copy the access token, and use Swagger's Authorize control with a bearer token. Get the application's current role and citizen UUID from `/api/v1/auth/me`.

`/health` is configuration-independent. `/ready` checks database connectivity and basic auth configuration; it does not certify that the AI service or worker is available.

## 6. Team integration

Member 4 calls only `/api/v1`. Configure its origin in `CORS_ORIGINS`. Member 3 supplies a persistent uploads volume at `UPLOAD_DIR`; private evidence is served only by authorized API routes.

Member 3's worker polls `GET /internal/jobs` using `X-API-Key: INTERNAL_API_KEY`, starts a job, calls identity/AI adapters, and posts its result or failure. Submission only queues work; no worker is started by this repository. Until Member 3 integrates a worker, cases remain submitted.

The worker must recheck consent before every provider call by requesting the start endpoint again. Stop on consent denial or stale generation. Start is replayable while processing. Call the failure endpoint on exhausted provider errors. There is no automatic retry scheduler or worker lease recovery in this implementation.

Mock Raast must consult `/internal/cases/{id}/payment-authorization` immediately before simulated transfer and independently enforce payment idempotency. No payment or notification is sent by this backend.

## 7. Before using the integrated demo

The user requested no testing during authoring. Installation, imports, schema compatibility and runtime behavior remain unverified. Run the acceptance scenarios in the implementation-status document once credentials and Member 2/3 services are ready.

Important current limits: one global internal worker key; no per-service scopes, request throttling or automatic job lease recovery; offset pagination; synthetic local evidence storage; no automatic notification enqueue; processing claims from the trusted worker are not independently verified against signed identity-provider evidence. Do not expose internal routes publicly without an infrastructure access restriction. Approval is deliberately conservative: unresolved identity/critical/evidence failures require successful reprocessing before approval.
