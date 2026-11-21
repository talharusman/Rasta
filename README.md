# RASTA

> **PROTOTYPE – not an official service.**
> This is a hackathon demo. All payments, people, and government services
> (NADRA, Raast, SMS) are **fake**.

A citizen claims a fictional relief payment.

- Backend: Python FastAPI + Postgres (SQLAlchemy)
- Frontend: React + Vite + TypeScript

## How to run

Backend (from the project root):

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux
pip install -r backend/requirements.txt
copy .env.example .env         # Windows   (Mac/Linux: cp .env.example .env)

# Configure the root .env, then migrate and seed before starting the worker.
(cd backend/platform/backend && alembic upgrade head)
(cd backend && python -m app.integrations.mocks.fixtures)
(cd backend && RUN_JOB_WORKER=true uvicorn main:app)
```

Open http://localhost:8000/docs. See the [platform setup guide](backend/platform/docs/SETUP.md) for Supabase demo users and worker configuration.

Frontend (in a second terminal):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Run the tests from the repository root with `python -m pytest tests -q`.

**Team guide: read [HOW_TO_WORK.md](HOW_TO_WORK.md).**
