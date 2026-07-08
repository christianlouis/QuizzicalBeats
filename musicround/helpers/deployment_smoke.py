"""External deployment smoke checks for production server hardening."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import perf_counter
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


TEXT_MIMETYPE_PREFIXES = (
    "application/json",
    "application/javascript",
    "text/",
)
MAX_SMOKE_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class SmokeResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: float = 0.0
    final_url: str | None = None


Fetcher = Callable[[str, dict[str, str] | None, float], SmokeResponse]


def _header(headers: dict[str, str], name: str) -> str:
    return headers.get(name.lower(), "")


def _normalize_headers(headers) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in dict(headers).items()}


def _fetch_url(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> SmokeResponse:
    started = perf_counter()
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_SMOKE_BODY_BYTES)
            return SmokeResponse(
                url=url,
                status=response.status,
                headers=_normalize_headers(response.headers),
                body=body,
                elapsed_ms=(perf_counter() - started) * 1000,
                final_url=response.geturl(),
            )
    except HTTPError as exc:
        return SmokeResponse(
            url=url,
            status=exc.code,
            headers=_normalize_headers(exc.headers),
            body=exc.read(MAX_SMOKE_BODY_BYTES),
            elapsed_ms=(perf_counter() - started) * 1000,
            final_url=exc.geturl(),
        )
    except (OSError, URLError) as exc:
        reason = getattr(exc, "reason", exc)
        return SmokeResponse(
            url=url,
            status=0,
            headers={},
            body=str(reason).encode("utf-8", errors="replace"),
            elapsed_ms=(perf_counter() - started) * 1000,
            final_url=url,
        )


def _check(name: str, ok: bool, message: str, **details) -> dict[str, object]:
    return {
        "name": name,
        "ok": ok,
        "message": message,
        "details": {key: value for key, value in details.items() if value is not None},
    }


def _is_text_response(response: SmokeResponse) -> bool:
    content_type = _header(response.headers, "content-type").split(";", 1)[0].strip()
    return any(content_type.startswith(prefix) for prefix in TEXT_MIMETYPE_PREFIXES)


def _safe_json(body: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _transport_error(response: SmokeResponse) -> str | None:
    if response.status != 0:
        return None
    return response.body.decode("utf-8", errors="replace") or "transport error"


def _validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL.")
    return base_url.rstrip("/") + "/"


def run_deployment_smoke(
    base_url: str,
    *,
    timeout: float = 10.0,
    require_hsts: bool | None = None,
    static_path: str = "/static/favicon.ico",
    compression_path: str = "/users/login",
    fetcher: Fetcher | None = None,
) -> dict[str, object]:
    """Run public deployment smoke checks for production server hardening."""
    normalized_base_url = _validate_base_url(base_url)
    parsed_base = urlparse(normalized_base_url)
    require_hsts = parsed_base.scheme == "https" if require_hsts is None else require_hsts
    fetch = fetcher or _fetch_url

    root_response = fetch(normalized_base_url, None, timeout)
    health_response = fetch(urljoin(normalized_base_url, "/healthz"), None, timeout)
    static_response = fetch(urljoin(normalized_base_url, static_path), None, timeout)
    compression_response = fetch(
        urljoin(normalized_base_url, compression_path),
        {"Accept-Encoding": "gzip"},
        timeout,
    )

    health_payload = _safe_json(health_response.body)
    health_ok = bool(health_payload.get("ok")) and 200 <= health_response.status < 500
    checks = [
        _check(
            "healthz",
            health_ok,
            "Health endpoint reports an operable deployment."
            if health_ok
            else "Health endpoint is failing.",
            status=health_response.status,
            transport_error=_transport_error(health_response),
            services=health_payload.get("services"),
            elapsed_ms=round(health_response.elapsed_ms, 3),
        )
    ]

    security_headers = {
        "x-content-type-options": "nosniff",
        "x-frame-options": None,
        "referrer-policy": None,
        "permissions-policy": None,
    }
    missing = []
    mismatched = []
    for name, expected in security_headers.items():
        value = _header(root_response.headers, name)
        if not value:
            missing.append(name)
        elif expected and value.lower() != expected:
            mismatched.append({"header": name, "expected": expected, "actual": value})
    if require_hsts and not _header(root_response.headers, "strict-transport-security"):
        missing.append("strict-transport-security")
    security_ok = not missing and not mismatched and 200 <= root_response.status < 400
    checks.append(
        _check(
            "security_headers",
            security_ok,
            "Security headers are present." if security_ok else "Security headers are incomplete.",
            status=root_response.status,
            transport_error=_transport_error(root_response),
            missing=missing,
            mismatched=mismatched,
            elapsed_ms=round(root_response.elapsed_ms, 3),
        )
    )

    server_header = _header(root_response.headers, "server").lower()
    dev_server_detected = "werkzeug" in server_header or "development" in server_header
    server_ok = bool(server_header) and not dev_server_detected
    checks.append(
        _check(
            "production_server",
            server_ok,
            "Server header does not look like Flask development server."
            if server_ok
            else "Server header is missing or looks like a development server.",
            server=_header(root_response.headers, "server") or None,
            transport_error=_transport_error(root_response),
        )
    )

    cache_control = _header(static_response.headers, "cache-control").lower()
    static_ok = (
        200 <= static_response.status < 400
        and "public" in cache_control
        and "max-age=" in cache_control
    )
    checks.append(
        _check(
            "static_asset_cache",
            static_ok,
            "Static asset cache headers are present."
            if static_ok
            else "Static asset cache headers are missing.",
            status=static_response.status,
            transport_error=_transport_error(static_response),
            cache_control=_header(static_response.headers, "cache-control") or None,
            elapsed_ms=round(static_response.elapsed_ms, 3),
        )
    )

    compression_ok = (
        200 <= compression_response.status < 400
        and _is_text_response(compression_response)
        and _header(compression_response.headers, "content-encoding").lower() == "gzip"
        and "accept-encoding" in _header(compression_response.headers, "vary").lower()
    )
    checks.append(
        _check(
            "response_compression",
            compression_ok,
            "Text responses are gzipped when requested."
            if compression_ok
            else "Text response compression was not observed on the configured path.",
            status=compression_response.status,
            transport_error=_transport_error(compression_response),
            content_type=_header(compression_response.headers, "content-type") or None,
            content_encoding=_header(compression_response.headers, "content-encoding") or None,
            vary=_header(compression_response.headers, "vary") or None,
            path=compression_path,
            elapsed_ms=round(compression_response.elapsed_ms, 3),
        )
    )

    failed = [check for check in checks if not check["ok"]]
    return {
        "ok": not failed,
        "base_url": normalized_base_url,
        "checks": checks,
        "failed_checks": failed,
        "guidance": [
            "Run after deploys to verify public health, proxy/security headers, "
            "static caching, and gzip behavior.",
            "Use --compression-path when the login page is not public or not representative.",
        ],
    }
