import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "endpoints" in response.json()

def test_search_no_api_key():
    response = client.post("/search", json={"topic": "AI", "max_results": 3})
    assert response.status_code == 401

def test_folders_no_api_key():
    response = client.get("/folders")
    assert response.status_code == 401