#!/usr/bin/env python3
"""
Migration: encrypt the Stripe secrets stored in the `settings` table (OWL-3).

Converts the plaintext `stripe_secret_key` and `stripe_webhook_secret` rows into
Fernet tokens, using the key in the SETTINGS_ENCRYPTION_KEY environment variable.

Safe to re-run: rows that are already encrypted are skipped. Each row is read
back and decrypted after writing, and the change is rolled back if that fails.

Usage:
    python migrate_encrypt_stripe_secrets.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Settings  # noqa: E402
from services.crypto import (  # noqa: E402
    encrypt_secret,
    decrypt_secret,
    is_encrypted,
    encryption_status,
    FERNET_ENV_VAR,
)

KEYS_TO_ENCRYPT = ['stripe_secret_key', 'stripe_webhook_secret']

EXPECTED_PREFIXES = {
    'stripe_secret_key': ('sk_', 'rk_'),
    'stripe_webhook_secret': ('whsec_',),
}

GENERATE_HINT = (
    '        python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


def preflight():
    """Refuse to touch the database unless encryption is actually usable."""
    state, message = encryption_status()
    if state != 'ok':
        print('[ERROR] %s - aborting before any changes' % message)
        print('[INFO] Generate a key with:')
        print(GENERATE_HINT)
        print('[INFO] Use the SAME %s everywhere that touches this database.' % FERNET_ENV_VAR)
        sys.exit(1)
    print('[OK] %s is configured' % FERNET_ENV_VAR)


def migrate_key(key):
    """Encrypt one settings row. Returns True if it was changed."""
    setting = Settings.query.filter_by(key=key).first()

    if setting is None:
        print('[INFO] %s: no row found - nothing to migrate' % key)
        return False

    if not setting.value:
        print('[INFO] %s: value is empty - nothing to migrate' % key)
        return False

    if is_encrypted(setting.value):
        print('[INFO] %s: already encrypted - skipping' % key)
        return False

    plaintext = setting.value
    if not plaintext.startswith(EXPECTED_PREFIXES[key]):
        print('[WARNING] %s: value does not look like the expected credential - '
              'encrypting anyway' % key)

    try:
        setting.value = encrypt_secret(plaintext)
        setting.updated_at = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print('[ERROR] %s: failed to encrypt - %s' % (key, e))
        raise

    # Read back and verify before declaring success - this is the only copy of a
    # live credential, so a write we cannot decrypt must not be left in place.
    db.session.expire_all()
    stored = Settings.query.filter_by(key=key).first()
    if not stored or decrypt_secret(stored.value) != plaintext:
        stored.value = plaintext
        db.session.commit()
        print('[ERROR] %s: encrypted value did not decrypt back to the original - '
              'reverted to the previous value' % key)
        sys.exit(1)

    print('[OK] %s: encrypted and verified' % key)
    return True


def main():
    preflight()

    app = create_app()
    with app.app_context():
        changed = 0
        for key in KEYS_TO_ENCRYPT:
            if migrate_key(key):
                changed += 1

    if changed:
        print('[SUCCESS] Migration complete - %d setting(s) encrypted' % changed)
    else:
        print('[SUCCESS] Migration complete - nothing to change')


if __name__ == '__main__':
    main()
