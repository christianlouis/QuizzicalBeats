"""Tests for email helper SMTP transport behavior."""
import smtplib

from musicround.helpers.email_helper import (
    EMAIL_CONFIGURATION_ERROR,
    EMAIL_DELIVERY_ERROR,
    send_email,
)


class FakeSmtpServer:
    """Small SMTP test double that records how it was used."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.sendmail_args = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, sender, recipient, message):
        self.sendmail_args = (sender, recipient, message)


class FailingSmtpServer(FakeSmtpServer):
    """SMTP test double that fails during delivery."""

    def sendmail(self, sender, recipient, message):
        super().sendmail(sender, recipient, message)
        raise smtplib.SMTPException('smtp password=secret failed')


def _configure_mail(app, use_tls=False, use_ssl=False):
    app.config.update(
        MAIL_HOST='smtp.example.test',
        MAIL_PORT=465 if use_ssl else 587,
        MAIL_USERNAME='mailer',
        MAIL_PASSWORD='secret',
        MAIL_SENDER='sender@example.test',
        MAIL_USE_TLS=use_tls,
        MAIL_USE_SSL=use_ssl,
    )


def test_send_email_uses_smtp_ssl_when_configured(app, monkeypatch):
    """Test implicit TLS uses SMTP_SSL and does not call STARTTLS."""
    _configure_mail(app, use_tls=False, use_ssl=True)
    FakeSmtpServer.instances = []

    def unexpected_smtp(*_args, **_kwargs):
        raise AssertionError("SMTP should not be used when MAIL_USE_SSL is enabled")

    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP', unexpected_smtp)
    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP_SSL', FakeSmtpServer)

    success, message = send_email('to@example.test', 'Subject', 'Body')

    assert success is True
    assert message == 'Email sent successfully to to@example.test!'
    server = FakeSmtpServer.instances[0]
    assert server.host == 'smtp.example.test'
    assert server.port == 465
    assert server.timeout == 30
    assert server.starttls_called is False
    assert server.login_args == ('mailer', 'secret')
    assert server.sendmail_args[0:2] == ('sender@example.test', 'to@example.test')


def test_send_email_uses_starttls_only_when_configured(app, monkeypatch):
    """Test STARTTLS is controlled by MAIL_USE_TLS."""
    _configure_mail(app, use_tls=True, use_ssl=False)
    FakeSmtpServer.instances = []

    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP', FakeSmtpServer)

    success, _message = send_email('to@example.test', 'Subject', 'Body')

    assert success is True
    assert FakeSmtpServer.instances[0].starttls_called is True


def test_send_email_plain_smtp_does_not_start_tls_when_disabled(app, monkeypatch):
    """Test plain SMTP remains possible for local mail relays."""
    _configure_mail(app, use_tls=False, use_ssl=False)
    FakeSmtpServer.instances = []

    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP', FakeSmtpServer)

    success, _message = send_email('to@example.test', 'Subject', 'Body')

    assert success is True
    assert FakeSmtpServer.instances[0].starttls_called is False


def test_send_email_returns_safe_message_for_missing_configuration(app):
    """Missing SMTP configuration should not leak exact missing secret names."""
    app.config.update(
        MAIL_HOST=None,
        MAIL_PORT=None,
        MAIL_USERNAME=None,
        MAIL_PASSWORD=None,
        MAIL_SENDER=None,
    )

    success, message = send_email('to@example.test', 'Subject', 'Body')

    assert success is False
    assert message == EMAIL_CONFIGURATION_ERROR
    assert 'MAIL_PASSWORD' not in message
    assert 'MAIL_HOST' not in message


def test_send_email_returns_safe_message_for_smtp_errors(app, monkeypatch):
    """SMTP exception details should stay in logs, not helper return values."""
    _configure_mail(app)
    FakeSmtpServer.instances = []

    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP', FailingSmtpServer)

    success, message = send_email('to@example.test', 'Subject', 'Body')

    assert success is False
    assert message == EMAIL_DELIVERY_ERROR
    assert 'secret' not in message
    assert 'password' not in message


def test_send_email_returns_safe_message_for_unexpected_transport_errors(app, monkeypatch):
    """Unexpected transport errors should return the same safe delivery message."""
    _configure_mail(app)

    def failing_smtp(*_args, **_kwargs):
        raise RuntimeError('socket token=transport-secret failed')

    monkeypatch.setattr('musicround.helpers.email_helper.smtplib.SMTP', failing_smtp)

    success, message = send_email('to@example.test', 'Subject', 'Body')

    assert success is False
    assert message == EMAIL_DELIVERY_ERROR
    assert 'transport-secret' not in message
    assert 'token' not in message
