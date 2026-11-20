# rasta

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

cd backend
uvicorn main:app --reload
```

Open http://localhost:8000/docs — you should see the health endpoints for
`platform`, `ai` and `mock`.

Frontend (in a second terminal):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Run the tests (from `backend/`): `python -m pytest`

The backend starts even without Postgres. You only need a database once you
add real tables.

**Team guide: read [HOW_TO_WORK.md](HOW_TO_WORK.md).**
