"""Authenticated streamable HTTP entrypoint for the Quizzical Beats MCP server."""

from __future__ import annotations

import os
import time
from secrets import compare_digest

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from musicround.mcp_server import mcp


_BASE_ALLOWED_HOSTS = tuple(mcp.settings.transport_security.allowed_hosts)
_BASE_ALLOWED_ORIGINS = tuple(mcp.settings.transport_security.allowed_origins)
_AUTH_FAILURES: dict[str, list[float]] = {}


def _prune_attempts(now: float, window_seconds: int) -> None:
    for key, attempts in list(_AUTH_FAILURES.items()):
        recent_attempts = [
            timestamp for timestamp in attempts if now - timestamp < window_seconds
        ]
        if recent_attempts:
            _AUTH_FAILURES[key] = recent_attempts
        else:
            _AUTH_FAILURES.pop(key, None)


def _rate_limited(key: str, max_attempts: int, window_seconds: int) -> bool:
    if max_attempts <= 0:
        return False
    now = time.time()
    _prune_attempts(now, window_seconds)
    return len(_AUTH_FAILURES.get(key, [])) >= max_attempts


def _record_auth_failure(key: str, window_seconds: int) -> None:
    now = time.time()
    _prune_attempts(now, window_seconds)
    _AUTH_FAILURES.setdefault(key, []).append(now)


def _clear_auth_failures(key: str) -> None:
    _AUTH_FAILURES.pop(key, None)


def _client_rate_limit_id(scope: Scope, headers: dict[bytes, bytes]) -> str:
    forwarded_for = headers.get(b"x-forwarded-for", b"").decode("latin1")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


class BearerAuthMiddleware:
    """Require a bearer token for MCP HTTP traffic."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") == "/healthz":
            await JSONResponse({"ok": True})(scope, receive, send)
            return

        expected = os.getenv("MCP_BEARER_TOKEN") or os.getenv("AUTOMATION_TOKEN")
        if not expected:
            await JSONResponse(
                {"error": "MCP bearer token is not configured."},
                status_code=500,
            )(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        rate_limit_key = _client_rate_limit_id(scope, headers)
        max_attempts = int(
            os.getenv(
                "MCP_AUTH_RATE_LIMIT_ATTEMPTS",
                os.getenv("AUTOMATION_RATE_LIMIT_ATTEMPTS", "10"),
            )
        )
        window_seconds = int(
            os.getenv(
                "MCP_AUTH_RATE_LIMIT_WINDOW_SECONDS",
                os.getenv("AUTOMATION_RATE_LIMIT_WINDOW_SECONDS", "300"),
            )
        )
        if _rate_limited(rate_limit_key, max_attempts, window_seconds):
            await JSONResponse(
                {"error": "Too many authentication attempts."},
                status_code=429,
            )(scope, receive, send)
            return

        authorization = headers.get(b"authorization", b"").decode("latin1")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not compare_digest(token.strip(), expected):
            _record_auth_failure(rate_limit_key, window_seconds)
            await JSONResponse(
                {"error": "Unauthorized."},
                headers={"WWW-Authenticate": "Bearer"},
                status_code=401,
            )(scope, receive, send)
            return

        _clear_auth_failures(rate_limit_key)
        await self.app(scope, receive, send)


def _configure_server() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    mcp.settings.host = host
    mcp.settings.port = port

    allowed_hosts = [
        value.strip()
        for value in os.getenv("MCP_ALLOWED_HOSTS", "qb.kaufdeinquiz.com").split(",")
        if value.strip()
    ]
    allowed_origins = [
        value.strip()
        for value in os.getenv(
            "MCP_ALLOWED_ORIGINS", "https://qb.kaufdeinquiz.com"
        ).split(",")
        if value.strip()
    ]
    security = mcp.settings.transport_security
    security.allowed_hosts = list(dict.fromkeys([*_BASE_ALLOWED_HOSTS, *allowed_hosts]))
    security.allowed_origins = list(
        dict.fromkeys([*_BASE_ALLOWED_ORIGINS, *allowed_origins])
    )


def build_app() -> ASGIApp:
    """Build the authenticated streamable HTTP MCP ASGI app."""
    _configure_server()
    return BearerAuthMiddleware(mcp.streamable_http_app())


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
