"""Logging helpers that keep credentials out of application logs."""

from collections.abc import Mapping


def oauth_token_log_summary(token):
    """Return non-sensitive OAuth token metadata for logs."""
    if token is None:
        return {"type": "none", "present": False}

    if isinstance(token, Mapping):
        return {
            "type": "mapping",
            "keys": sorted(str(key) for key in token.keys()),
            "has_access_token": bool(token.get("access_token")),
            "has_refresh_token": bool(token.get("refresh_token")),
            "has_id_token": bool(token.get("id_token")),
            "expires_at": token.get("expires_at"),
            "expires_in": token.get("expires_in"),
            "token_type": token.get("token_type"),
            "scope": token.get("scope"),
        }

    if isinstance(token, str):
        return {
            "type": "string",
            "present": bool(token),
            "length": len(token),
        }

    return {
        "type": type(token).__name__,
        "present": True,
    }


def redact_authorization_header(headers):
    """Return a copy of headers with Authorization values removed."""
    redacted = dict(headers or {})
    if "Authorization" in redacted:
        redacted["Authorization"] = "[redacted]"
    return redacted
