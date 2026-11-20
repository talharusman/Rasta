# OWNER: Member 2
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/ai/health").status_code == 200


def test_decide_is_human():
    response = client.post("/api/ai/decide")
    assert response.json()["route"] == "HUMAN"
