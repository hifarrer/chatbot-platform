"""
Encryption helpers for secret values stored in the `settings` table.

Secrets (currently the Stripe secret key and webhook secret) are encrypted at
rest with Fernet, keyed from the SETTINGS_ENCRYPTION_KEY environment variable.

Behaviour when the key is missing or invalid:
  - reads  fail soft  -> decrypt_secret() returns '' so the app stays up and
                         payments degrade to the existing "not configured" path
  - writes fail loud   -> encrypt_secret() raises, so a live key can never be
                         stored as plaintext while the operator believes it is
                         encrypted

Legacy plaintext values are passed through unchanged on read, so an environment
that has the new code but has not run migrate_encrypt_stripe_secrets.py yet
keeps working.
"""
import os

# Optional cryptography dependency (guarded, same style as the stripe import in app.py)
try:
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except Exception:  # pragma: no cover - only hit when the package is absent
    Fernet = None
    InvalidToken = Exception

FERNET_ENV_VAR = 'SETTINGS_ENCRYPTION_KEY'

# Settings rows that are stored encrypted. Documentation + the migration's allowlist.
SECRET_SETTING_KEYS = ('stripe_secret_key', 'stripe_webhook_secret')

# Every Fernet token starts with base64url of 0x80 + an 8-byte timestamp, which
# always renders as this prefix. Used as a routing hint only - the InvalidToken
# catch in decrypt_secret() is the real guarantee.
_FERNET_PREFIX = 'gAAAAA'

_fernet = None
_fernet_error = None
_fernet_loaded = False
_decrypt_error_logged = False


def _load_fernet():
    """Build (and cache) the Fernet instance. Lazy so load_dotenv() has already run."""
    global _fernet, _fernet_error, _fernet_loaded
    if _fernet_loaded:
        return _fernet

    _fernet_loaded = True
    if Fernet is None:
        _fernet_error = 'no_library'
        return None

    raw_key = (os.environ.get(FERNET_ENV_VAR) or '').strip()
    if not raw_key:
        _fernet_error = 'missing_key'
        return None

    try:
        _fernet = Fernet(raw_key.encode('utf-8'))
    except Exception:
        _fernet = None
        _fernet_error = 'invalid_key'
    return _fernet


def encryption_status():
    """Return (status, message) where status is ok|no_library|missing_key|invalid_key."""
    _load_fernet()
    if _fernet is not None:
        return 'ok', 'Settings encryption is configured'
    if _fernet_error == 'no_library':
        return 'no_library', "The 'cryptography' package is not installed"
    if _fernet_error == 'invalid_key':
        return 'invalid_key', (
            '%s is set but is not a valid Fernet key '
            '(expected 32 url-safe base64-encoded bytes)' % FERNET_ENV_VAR
        )
    return 'missing_key', '%s is not set' % FERNET_ENV_VAR


def is_encrypted(value):
    """True if the stored value looks like a Fernet token rather than plaintext."""
    return isinstance(value, str) and value.startswith(_FERNET_PREFIX)


def encrypt_secret(plaintext):
    """
    Encrypt a secret for storage. Raises RuntimeError if encryption is unavailable
    so a secret is never silently written as plaintext.
    """
    if not plaintext:
        # Empty stays unambiguously empty, so "is configured?" is a plain
        # truthiness test on the raw column.
        return ''
    if is_encrypted(plaintext):
        # Already a token - makes the migration and re-saves idempotent.
        return plaintext

    fernet = _load_fernet()
    if fernet is None:
        status, message = encryption_status()
        # Message must never contain the plaintext: app.py interpolates str(e)
        # into the admin settings JSON response.
        raise RuntimeError('Cannot encrypt setting - %s' % message)

    return fernet.encrypt(str(plaintext).encode('utf-8')).decode('utf-8')


def decrypt_secret(stored):
    """
    Decrypt a stored secret. Never raises - callers run inside request handlers.
    Legacy plaintext values are returned unchanged.
    """
    global _decrypt_error_logged

    if not stored:
        return ''
    if not is_encrypted(stored):
        # Legacy plaintext, written before the encryption migration ran.
        return stored

    fernet = _load_fernet()
    if fernet is None:
        if not _decrypt_error_logged:
            _decrypt_error_logged = True
            status, message = encryption_status()
            print('[ERROR] Cannot decrypt stored setting - %s' % message)
        return ''

    try:
        return fernet.decrypt(stored.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        print('[ERROR] Failed to decrypt stored setting - wrong %s?' % FERNET_ENV_VAR)
        return ''
    except Exception as e:
        print('[ERROR] Failed to decrypt stored setting: %s' % type(e).__name__)
        return ''
