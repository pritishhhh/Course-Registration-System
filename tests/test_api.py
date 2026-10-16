import base64
import json
from contextlib import contextmanager
from unittest.mock import Mock

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

import app as api
from server import auth


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    with TestClient(api.app) as client:
        yield client
    api.app.dependency_overrides.clear()


def verified_user():
    return {"id": "00000000-0000-0000-0000-000000000001", "email": "verified@example.test", "email_confirmed_at": "2026-01-01T00:00:00Z"}


def mock_auth(monkeypatch, status=200, data=None):
    response = httpx.Response(status, json=verified_user() if data is None else data,
                              request=httpx.Request("GET", "https://example.supabase.co/auth/v1/user"))
    monkeypatch.setattr(auth.httpx, "get", Mock(return_value=response))


def test_web_and_public_config(client):
    assert client.get("/").status_code == 200
    assert "Course Registration" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/docs-init.js").status_code == 200
    assert "<script>" not in client.get("/docs").text  # Compatible with strict CSP.
    assert set(client.get("/api/config").json()) == {"supabase_url", "supabase_key"}
    assert client.get("/api/config").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("key", ["sb_secret_private", "invalid", "x." + base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode() + ".x"])
def test_privileged_key_is_never_exposed(client, monkeypatch, key):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", key)
    response = client.get("/api/config")
    assert response.status_code == 503
    assert key not in response.text


@pytest.mark.parametrize("method,path", [("get", "/api/me/enrollments"), ("post", "/api/sections/1/register"), ("delete", "/api/sections/1/registration")])
def test_auth_required(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_bad_token_and_auth_outage(client, monkeypatch):
    mock_auth(monkeypatch, 401, {})
    headers = {"Authorization": "Bearer forged"}
    assert client.get("/api/me/enrollments", headers=headers).status_code == 401
    mock_auth(monkeypatch, 500, {})
    assert client.get("/api/me/enrollments", headers=headers).status_code == 503


def test_unconfirmed_user_rejected(client, monkeypatch):
    user = verified_user(); user["email_confirmed_at"] = None
    mock_auth(monkeypatch, data=user)
    assert client.get("/api/me/enrollments", headers={"Authorization": "Bearer valid"}).status_code == 403


def test_missing_database_is_actionable(client, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client.get("/api/health").status_code == 503


@pytest.mark.parametrize("section", [0, -1, 2147483648, "garbage"])
def test_section_validation(client, section):
    api.app.dependency_overrides[auth.current_user] = lambda: {"subject": "test", "email": "test@example.test"}
    assert client.post(f"/api/sections/{section}/register").status_code == 422


def test_database_details_are_redacted(client, monkeypatch):
    @contextmanager
    def failure():
        raise psycopg.OperationalError("postgres://user:secret@private-host")
        yield
    monkeypatch.setattr(api, "transaction", failure)
    response = client.get("/api/sections")
    assert response.status_code == 503
    assert "secret" not in response.text and "private-host" not in response.text


def test_end_to_end_student_isolation(client, monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", database)
    mock_auth(monkeypatch)
    headers = {"Authorization": "Bearer real-user"}
    assert client.get("/api/sections").status_code == 200
    response = client.post("/api/sections/1/register?student_id=2", json={"student_id": 2}, headers=headers)
    assert response.json() == {"result": "ENROLLED"}
    assert client.post("/api/sections/1/register", headers=headers).json() == {"result": "ALREADY_ENROLLED"}
    assert len(client.get("/api/me/enrollments", headers=headers).json()) == 1
    user = verified_user(); user["id"] = "00000000-0000-0000-0000-000000000002"; user["email"] = "other@example.test"
    mock_auth(monkeypatch, data=user)
    assert client.get("/api/me/enrollments", headers=headers).json() == []
    assert client.delete("/api/sections/1/registration", headers=headers).json() == {"result": "NOT_ENROLLED"}
    mock_auth(monkeypatch)
    assert client.delete("/api/sections/1/registration", headers=headers).json() == {"result": "DROPPED"}
