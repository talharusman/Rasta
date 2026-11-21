# OWNER: Member 3. Backend image for Railway (and any Docker host).
# Build context is the repo root. The app lives in backend/ and is started from there.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Install dependencies first (cached until a requirements file changes).
# backend/requirements.txt pulls in the three per-member files with "-r", so copy all four.
COPY backend/requirements.txt ./requirements.txt
COPY backend/platform/requirements.txt ./platform/requirements.txt
COPY backend/ai/requirements.txt ./ai/requirements.txt
COPY backend/mocks/requirements.txt ./mocks/requirements.txt
RUN pip install -r requirements.txt

COPY backend/ ./

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

# Railway sets $PORT. Use the `uvicorn` command (not `python -m uvicorn`): from this folder,
# `python -m` would let backend/platform/ shadow Python's built-in "platform" module.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
