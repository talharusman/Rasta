# How we work together

Short and simple. Read it once. Come back when you are stuck.

## 1. Who owns what

| Member   | Folder              | Git branch    |
|----------|---------------------|---------------|
| Member 1 | `backend/platform/` | `m1-platform` |
| Member 2 | `backend/ai/`       | `m2-ai`       |
| Member 3 | `backend/mocks/`    | `m3-mocks`    |
| Member 4 | `frontend/`         | `m4-frontend` |

## 2. Golden rule

**Only edit files inside your own folder.**
If you need to change `backend/shared/` or `main.py`, ask the team first.

## 3. First-time setup

```bash
git clone <repo-url>
cd rasta
git checkout <your-branch>        # example: git checkout m2-ai
```

Backend:

```bash
python -m venv venv
venv\Scripts\activate             # Windows
# source venv/bin/activate        # Mac / Linux
pip install -r backend/requirements.txt
copy .env.example .env            # Windows   (Mac/Linux: cp .env.example .env)

cd backend
uvicorn main:app --reload
```

Open http://localhost:8000/docs

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## 4. Daily work loop

1. Get your teammates' work:
   ```bash
   git pull origin dev
   ```
2. Work in your folder.
3. Save and upload your work:
   ```bash
   git add .
   git commit -m "[M2] what I did"
   git push origin <your-branch>
   ```
4. On GitHub, open a **Pull Request** from your branch into `dev`.

## 5. Merge often

**Merge into `dev` every 3–4 hours, not only at the end.**
Small merges are easy. One giant merge at hour 47 is a disaster.

## 6. Git shows a conflict?

Do not panic. A conflict means two people changed the same lines.
Git puts marks like `<<<<<<<` and `>>>>>>>` in the file.
You must choose which lines to keep and delete the marks.

If you are not sure: **stop and ask Member 1 for help.**
Do not use `git push --force`.

## 7. Add a new Python package

Put it in **your own folder's** `requirements.txt` only.
Example for Member 2: add a line to `backend/ai/requirements.txt`, then:

```bash
pip install -r backend/requirements.txt
```

## 8. Add a new API endpoint

Add it in **your own** `routes.py` only.
Example (Member 3, in `backend/mocks/routes.py`):

```python
@router.get("/hello")
def hello():
    return {"message": "hello"}
```

Save. The server reloads. Check it at http://localhost:8000/docs

## Database tables

You can add a table in your own `models.py`.
Only **Member 1** creates database migrations (Alembic, inside `backend/`).
Tell Member 1 when you add or change a table.

## One Python gotcha

Python already has a built-in module named `platform`.
So inside `backend/platform/`, Member 1 must use **relative imports**:
`from .models import Case` (not `from platform.models import Case`).
