# OWNER: Member 3
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/mock/health").status_code == 200


def test_nadra_verify():
    response = client.post("/api/mock/nadra/verify", json={"cnic": "99999-0000001-1"})
    assert response.json()["verified"] is True
