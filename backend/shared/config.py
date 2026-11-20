# OWNER: shared. Change only after telling the team.
# Reads settings from the ".env" file in the project root.
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rasta"
)
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
