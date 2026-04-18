from fastapi.testclient import TestClient

from jutra.api.main import app


def test_healthz_reports_gemini3_models() -> None:
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["models"]["chat"].startswith("gemini-3")
    assert body["models"]["reasoning"].startswith("gemini-3")
    assert body["models"]["embed"] == "text-embedding-005"
    assert body["locations"]["llm"] == "global"
    assert body["locations"]["embed"] == "europe-west4"
