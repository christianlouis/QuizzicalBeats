"""Tests for the authenticated MCP HTTP entrypoint."""

import os

from starlette.responses import Response
from starlette.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.mcp_http import BearerAuthMiddleware, build_app, mcp  # noqa: E402


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
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert accepted.status_code != 401


def test_mcp_falls_back_to_automation_token(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("AUTOMATION_TOKEN", "automation-token")
    client = TestClient(BearerAuthMiddleware(_dummy_app))

    accepted = client.get("/mcp", headers={"Authorization": "Bearer automation-token"})

    assert accepted.status_code == 204


def test_mcp_reports_missing_bearer_configuration(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("AUTOMATION_TOKEN", raising=False)
    client = TestClient(BearerAuthMiddleware(_dummy_app))

    response = client.get("/mcp", headers={"Authorization": "Bearer anything"})

    assert response.status_code == 500


def test_allowed_hosts_are_replaced_between_builds(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "first.example")
    build_app()
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "second.example")
    build_app()

    assert "first.example" not in mcp.settings.transport_security.allowed_hosts
    assert "second.example" in mcp.settings.transport_security.allowed_hosts
