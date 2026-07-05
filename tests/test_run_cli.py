"""Tests for the management CLI."""

import json
import sys


def test_health_check_command_outputs_public_safe_json(app, monkeypatch, capsys):
    """The documented health CLI should share the /healthz payload."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "health", "check"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["services"]["database"]["status"] == "ok"
    assert "password" not in output.lower()
    assert "token" not in output.lower()
