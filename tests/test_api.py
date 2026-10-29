from fastapi.testclient import TestClient

from resume_tailor.api import app

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tailor_endpoint_reports_missing_agent_configuration() -> None:
    response = client.post(
        "/api/tailor",
        json={
            "resume_text": "A resume draft",
            "job_description": "A role description",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "No model provider is configured for the resume tailoring agent."
    )