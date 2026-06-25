import httpx

def test_health():
    response = httpx.get("http://localhost:8765/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    