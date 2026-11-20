# OWNER: Member 1
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/platform/health")
    assert response.status_code == 200
    assert response.json()["service"] == "platform"
