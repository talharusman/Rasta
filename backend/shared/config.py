# OWNER: shared. Change only after telling the team.
# Reads settings from the ".env" file in the project root.
import os
from pathlib import Path

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[2]
load_dotenv(root / ".env")
load_dotenv(root / "backend/platform/backend/.env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rasta"
)
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
