"""Tests for external deployment smoke checks."""

import json

import pytest

from musicround.helpers.deployment_smoke import SmokeResponse, run_deployment_smoke


def _response(status=200, headers=None, body=b"", url="https://qb.example.test/"):
    return SmokeResponse(
        url=url,
        final_url=url,
        status=status,
        headers={key.lower(): value for key, value in (headers or {}).items()},
        body=body,
        elapsed_ms=12.5,
    )


def _healthy_fetcher(url, headers=None, timeout=10.0):
    if url.endswith("/healthz"):
        return _response(
            headers={"content-type": "application/json"},
            body=json.dumps({"ok": True, "services": {"database": {"status": "ok"}}}).encode(),
            url=url,
        )
    if url.endswith("/static/favicon.ico"):
        return _response(
            headers={
                "cache-control": "no-cache, public, max-age=86400",
                "content-type": "image/vnd.microsoft.icon",
            },
            body=b"icon",
            url=url,
        )
    if url.endswith("/users/login"):
        return _response(
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-encoding": "gzip",
                "vary": "Accept-Encoding, Cookie",
            },
            body=b"compressed",
            url=url,
        )
    return _response(
        status=302,
        headers={
            "server": "gunicorn",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "strict-origin-when-cross-origin",
            "permissions-policy": "camera=()",
            "strict-transport-security": "max-age=31536000",
        },
        body=b"",
        url=url,
    )


def test_deployment_smoke_passes_for_hardened_public_deployment():
    result = run_deployment_smoke("https://qb.example.test", fetcher=_healthy_fetcher)

    assert result["ok"] is True
    assert result["failed_checks"] == []
    assert {check["name"] for check in result["checks"]} == {
        "healthz",
        "security_headers",
        "production_server",
        "static_asset_cache",
        "response_compression",
    }


def test_deployment_smoke_reports_missing_security_headers():
    def fetcher(url, headers=None, timeout=10.0):
        response = _healthy_fetcher(url, headers=headers, timeout=timeout)
        if url == "https://qb.example.test/":
            return _response(status=200, headers={"server": "Werkzeug"}, body=b"", url=url)
        return response

    result = run_deployment_smoke("https://qb.example.test", fetcher=fetcher)

    assert result["ok"] is False
    failed_names = {check["name"] for check in result["failed_checks"]}
    assert {"security_headers", "production_server"}.issubset(failed_names)


def test_deployment_smoke_rejects_relative_base_url():
    with pytest.raises(ValueError, match="absolute http"):
        run_deployment_smoke("/relative", fetcher=_healthy_fetcher)


def test_deployment_smoke_reports_transport_errors_without_crashing():
    def fetcher(url, headers=None, timeout=10.0):
        if url.endswith("/static/favicon.ico"):
            return _response(status=0, body=b"connection reset", url=url)
        return _healthy_fetcher(url, headers=headers, timeout=timeout)

    result = run_deployment_smoke("https://qb.example.test", fetcher=fetcher)

    assert result["ok"] is False
    static_check = next(
        check for check in result["failed_checks"] if check["name"] == "static_asset_cache"
    )
    assert static_check["details"]["transport_error"] == "connection reset"
