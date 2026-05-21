"""Authenticated streamable HTTP entrypoint for the Quizzical Beats MCP server."""

from __future__ import annotations

import os
from secrets import compare_digest

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from musicround.mcp_server import mcp


_BASE_ALLOWED_HOSTS = tuple(mcp.settings.transport_security.allowed_hosts)
_BASE_ALLOWED_ORIGINS = tuple(mcp.settings.transport_security.allowed_origins)


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
        authorization = headers.get(b"authorization", b"").decode("latin1")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not compare_digest(token.strip(), expected):
            await JSONResponse(
                {"error": "Unauthorized."},
                headers={"WWW-Authenticate": "Bearer"},
                status_code=401,
            )(scope, receive, send)
            return

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
