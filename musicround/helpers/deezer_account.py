"""Per-user Deezer OAuth storage and token access."""

import base64
import hashlib
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from flask_login import current_user

from musicround.models import DeezerAccount, db


class DeezerAccountError(RuntimeError):
    """Raised when a stored Deezer connection cannot be used."""


def _fernet():
    configured = current_app.config.get('DEEZER_TOKEN_ENCRYPTION_KEY')
    if configured:
        key = configured.encode() if isinstance(configured, str) else configured
    else:
        secret = current_app.config.get('SECRET_KEY')
        if not secret:
            raise DeezerAccountError('Deezer token encryption is not configured.')
        key = base64.urlsafe_b64encode(hashlib.sha256(str(secret).encode()).digest())
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise DeezerAccountError('Deezer token encryption is not configured correctly.') from exc


def encrypt_deezer_token(access_token):
    """Encrypt a Deezer OAuth access token for database storage."""
    if not access_token:
        raise DeezerAccountError('Deezer returned an empty access token.')
    return _fernet().encrypt(access_token.encode()).decode()


def decrypt_deezer_token(account):
    """Decrypt a stored Deezer token without exposing it to templates or logs."""
    try:
        return _fernet().decrypt(account.access_token_ciphertext.encode()).decode()
    except (InvalidToken, UnicodeDecodeError, AttributeError) as exc:
        raise DeezerAccountError('The Deezer connection is invalid. Please reconnect Deezer.') from exc


def get_current_user_deezer_account():
    """Return ``(account_id, access_token)`` for the signed-in user, if connected."""
    if not current_user.is_authenticated:
        return None
    account = DeezerAccount.query.filter_by(user_id=current_user.id).first()
    if not account:
        return None
    if account.token_expires_at and account.token_expires_at <= datetime.utcnow():
        return None
    try:
        return str(account.account_id), decrypt_deezer_token(account)
    except DeezerAccountError:
        return None


def save_deezer_account(user_id, account_id, access_token, token_expires_at=None):
    """Create or replace one user's encrypted Deezer connection."""
    account = DeezerAccount.query.filter_by(user_id=user_id).first()
    if account is None:
        account = DeezerAccount(user_id=user_id)
        db.session.add(account)
    account.account_id = str(account_id)
    account.access_token_ciphertext = encrypt_deezer_token(access_token)
    account.token_expires_at = token_expires_at
    db.session.commit()
    return account
