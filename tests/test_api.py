from fastapi.testclient import TestClient

from sesourcer.fetch import FetchError, assert_public_http_url, fetch_job_text
from sesourcer.server import app


def test_limit_defaults_to_20(monkeypatch):
    captured = {}

    def fake_run(text, notes, limit, page_title=None):
        captured["limit"] = limit
        captured["notes"] = notes
        return {
            "brief": {"title": "Engineer", "must_have": [], "locations": []},
            "queries": [],
            "candidates": [],
            "requested": limit,
            "returned": 0,
            "pool_size": 0,
            "warnings": [],
            "source_note": "public snippets",
        }

    monkeypatch.setattr("sesourcer.server.run_search", fake_run)
    response = TestClient(app).post("/api/search", json={"job_text": "Senior software engineer in London"})
    assert response.status_code == 200
    assert captured["limit"] == 20


def test_custom_limit_is_passed_through(monkeypatch):
    captured = {}

    def fake_run(text, notes, limit, page_title=None):
        captured["limit"] = limit
        return {
            "brief": {"title": "Engineer", "must_have": []},
            "queries": [],
            "candidates": [],
            "requested": limit,
            "returned": 0,
            "pool_size": 0,
            "warnings": [],
            "source_note": "",
        }

    monkeypatch.setattr("sesourcer.server.run_search", fake_run)
    response = TestClient(app).post(
        "/api/search",
        json={"job_text": "Designer in Berlin", "limit": 7, "notes": "Figma"},
    )
    assert response.status_code == 200
    assert captured["limit"] == 7


def test_empty_request_is_rejected():
    response = TestClient(app).post("/api/search", json={})
    assert response.status_code == 400


def test_linkedin_job_links_are_refused_without_a_request():
    try:
        fetch_job_text("https://www.linkedin.com/jobs/view/123")
    except FetchError as exc:
        assert "Paste the job description" in str(exc)
    else:
        raise AssertionError("LinkedIn URL should be refused")


def test_private_urls_are_refused():
    for url in (
        "http://127.0.0.1/latest",
        "http://169.254.169.254/latest/meta-data",
        "http://10.1.2.3/",
        "http://192.168.0.4/",
        "file:///etc/passwd",
    ):
        try:
            assert_public_http_url(url)
        except FetchError:
            continue
        raise AssertionError(url)
