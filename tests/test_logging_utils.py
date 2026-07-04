from musicround.helpers.logging_utils import (
    oauth_token_log_summary,
    redact_authorization_header,
)


def test_oauth_token_log_summary_keeps_token_values_out():
    summary = oauth_token_log_summary(
        {
            "access_token": "spotify-access-secret",
            "refresh_token": "spotify-refresh-secret",
            "id_token": "spotify-id-secret",
            "expires_at": 1234567890,
            "expires_in": 3600,
            "scope": "playlist-read-private",
            "token_type": "Bearer",
        }
    )

    rendered = repr(summary)

    assert "spotify-access-secret" not in rendered
    assert "spotify-refresh-secret" not in rendered
    assert "spotify-id-secret" not in rendered
    assert summary["has_access_token"] is True
    assert summary["has_refresh_token"] is True
    assert summary["has_id_token"] is True
    assert summary["expires_in"] == 3600
    assert summary["token_type"] == "Bearer"


def test_oauth_token_log_summary_redacts_plain_token_strings():
    summary = oauth_token_log_summary("plain-bearer-secret")

    assert "plain-bearer-secret" not in repr(summary)
    assert summary == {
        "type": "string",
        "present": True,
        "length": len("plain-bearer-secret"),
    }


def test_redact_authorization_header_removes_bearer_value():
    headers = {
        "Authorization": "Bearer dropbox-access-secret",
        "Content-Type": "application/json",
    }

    redacted = redact_authorization_header(headers)

    assert redacted["Authorization"] == "[redacted]"
    assert redacted["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer dropbox-access-secret"
    assert "dropbox-access-secret" not in repr(redacted)
