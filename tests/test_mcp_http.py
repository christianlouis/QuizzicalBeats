"""Tests for the authenticated MCP HTTP entrypoint."""

import os

from starlette.responses import Response
from starlette.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.mcp_http import BearerAuthMiddleware, build_app  # noqa: E402


async def _dummy_app(scope, receive, send):
    await Response(status_code=204)(scope, receive, send)


def test_healthz_does_not_require_auth(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-mcp-token")
    client = TestClient(build_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_mcp_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-mcp-token")
    client = TestClient(BearerAuthMiddleware(_dummy_app))

    missing = client.get("/mcp")
    wrong = client.get("/mcp", headers={"Authorization": "Bearer wrong"})
    accepted = client.get("/mcp", headers={"Authorization": "Bearer test-mcp-token"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code != 401
