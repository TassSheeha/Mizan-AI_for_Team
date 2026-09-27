"""Test suite fixtures — isolated DB, fake AI layer, limiter reset per test."""

import os
import pathlib
import time

import pytest

TEST_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = TEST_DIR / "test_mizan.db"

# Must be set BEFORE importing app modules (config reads env at import time).
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci-only-32-bytes-long!!"
os.environ["ADMIN_EMAIL"] = "admin@test.ly"
os.environ["ADMIN_PASSWORD"] = "Admin@Test123"
os.environ["GROQ_API_KEY"] = ""
os.environ["MIZAN_TEST_MODE"] = "1"  # skip heavy ChromaDB/ONNX loading
if DB_PATH.exists():
    try:
        DB_PATH.unlink()
    except PermissionError:
        DB_PATH.unlink(missing_ok=True)

# Replace the heavy AI initialization (ChromaDB + ONNX + BM25) with a stub.
from app.services import ai as ai_mod  # noqa: E402


def _fake_initialize(self) -> None:
    self._assistant = None
    self._status = "ready"
    self._error = None


ai_mod.AIService._initialize = _fake_initialize

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    try:
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        limiter.reset()
    except Exception:
        pass


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    from app.db.models import engine

    engine.dispose()
    time.sleep(0.2)
    try:
        DB_PATH.unlink(missing_ok=True)
    except PermissionError:
        pass


def _register(client: TestClient, email: str, username: str, password: str = "Passw0rd!123"):
    res = client.post("/api/auth/register", json={
        "email": email, "username": username, "password": password,
    })
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture(scope="session")
def user_headers(client):
    data = _register(client, "user1@test.ly", "user1")
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.fixture(scope="session")
def second_user_headers(client):
    data = _register(client, "user2@test.ly", "user2")
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    res = client.post("/api/auth/login", json={
        "email": "admin@test.ly", "password": "Admin@Test123",
    })
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
