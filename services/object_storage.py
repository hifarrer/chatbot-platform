"""Object storage for everything a deploy must not destroy.

Uploaded documents, chatbot avatars and generated knowledge bases used to live
on the container filesystem, which Render rebuilds from git on every deploy -
so each release silently deleted every customer's files while Postgres went on
reporting their bots as trained. A persistent disk was tried and was worse than
useless: it was attached, and a mount-path mismatch meant nothing ever wrote to
it, silently.

Now there are exactly two backends and no probing:

  * BunnyBackend - two Bunny.net Edge Storage zones. A PUBLIC zone with a Pull
    Zone in front for avatars (fetched by browsers on customers' own sites), and
    a PRIVATE zone reachable only with an access key for uploaded documents and
    knowledge bases.
  * LocalBackend - plain directories, for development.

Which one is in use is decided by configuration alone and stated in the boot log
and on /health. A half-configured hosted instance raises at boot rather than
quietly writing to a filesystem that is about to be thrown away; that silent
fallback is the entire bug this module replaces.
"""
import hashlib
import io
import os
import re
import threading
import uuid
from urllib.parse import quote

import requests

from services.storage_retry import call_with_retry

PUBLIC = 'public'
PRIVATE = 'private'
ZONES = (PUBLIC, PRIVATE)

# Region hosts, for the error message when someone picks the wrong one. Bunny
# answers 401 for a wrong region exactly as it does for a wrong key, so the
# distinction has to come from us.
KNOWN_HOSTS = ('storage.bunnycdn.com', 'ny.storage.bunnycdn.com', 'la.storage.bunnycdn.com',
               'uk.storage.bunnycdn.com', 'se.storage.bunnycdn.com', 'br.storage.bunnycdn.com',
               'sg.storage.bunnycdn.com', 'syd.storage.bunnycdn.com', 'jh.storage.bunnycdn.com')

_INVALID_SEGMENT = re.compile(r'(^$|^\.$|^\.\.$)')

_backend = None
_backend_lock = threading.Lock()


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class StorageError(Exception):
    """A storage operation that failed. `code` maps to user-facing copy."""

    def __init__(self, message, *, op=None, key=None, zone=None,
                 code='storage_unavailable', status=None, attempts=1, retryable=False):
        super().__init__(message)
        self.op = op
        self.key = key
        self.zone = zone
        self.code = code
        self.status = status
        self.attempts = attempts
        self.retryable = retryable


class StorageNotFound(StorageError):
    """The object is not there. Never retried; often not an error at all."""

    def __init__(self, message, **kwargs):
        kwargs.setdefault('code', 'storage_not_found')
        kwargs.setdefault('retryable', False)
        super().__init__(message, **kwargs)


# ----------------------------------------------------------------------
# Keys
# ----------------------------------------------------------------------

def validate_key(key):
    """Reject anything that could escape its prefix. Returns the key.

    /uploads/<filename> takes a user-controlled filename straight into a key, so
    this is a real traversal boundary rather than a formality.
    """
    if not key or not isinstance(key, str):
        raise ValueError('storage key must be a non-empty string')
    if key.startswith('/') or chr(92) in key:
        raise ValueError(f'invalid storage key: {key!r}')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
        # Control characters have no business in a key built from a filename.
        raise ValueError(f'invalid storage key: {key!r}')
    for segment in key.split('/'):
        if _INVALID_SEGMENT.match(segment):
            raise ValueError(f'invalid storage key segment in {key!r}')
    return key


def document_key(chatbot_id, unique_filename):
    """Sharded by chatbot so deletion and orphan audits are one prefix listing."""
    return validate_key(f'documents/{int(chatbot_id)}/{unique_filename}')


def avatar_key(avatar_filename):
    """Flat, and the filename is preserved.

    /uploads/<filename> carries no chatbot id and must keep resolving for URLs
    customers have already pasted onto their own sites. Sharding avatars would
    force a database lookup on every avatar hit and break those URLs.
    """
    return validate_key(f'avatars/{avatar_filename}')


def artifact_key(chatbot_id):
    return validate_key(f'training/chatbot_{int(chatbot_id)}.json')


def _as_bytes(data):
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        return data.encode('utf-8')
    if hasattr(data, 'read'):
        return data.read()
    raise TypeError(f'cannot store {type(data).__name__}')


# ----------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------

class StorageBackend:
    """Duck-typed interface. Deliberately not an ABC - the fake in the test
    suite implements the same names without inheriting."""
    name = 'base'

    def put(self, zone, key, data, *, content_type=None, timeout=None, logger=None):
        raise NotImplementedError

    def get(self, zone, key, *, timeout=None, attempts=None, logger=None):
        raise NotImplementedError

    def delete(self, zone, key, *, logger=None):
        raise NotImplementedError

    def exists(self, zone, key):
        raise NotImplementedError

    def stat(self, zone, key):
        raise NotImplementedError

    def list(self, zone, prefix):
        raise NotImplementedError

    def public_url(self, zone, key):
        return None

    def describe(self):
        return {'backend': self.name}


class BunnyZone:
    def __init__(self, label, zone_name, access_key, host, cdn_base_url=None):
        self.label = label
        self.zone_name = zone_name
        self.access_key = access_key
        self.host = host
        self.cdn_base_url = (cdn_base_url or '').rstrip('/') or None

    @property
    def base_url(self):
        return f'https://{self.host}/{self.zone_name}/'


class BunnyBackend(StorageBackend):
    name = 'bunny'

    def __init__(self, zones, *, connect_timeout=5.0, read_timeout=30.0,
                 attempts=3, session=None):
        self.zones = zones
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.attempts = attempts
        # One session for keep-alive: on the chat path a fresh TLS handshake per
        # artifact fetch is most of the latency.
        self.session = session or requests.Session()

    # -- helpers ------------------------------------------------------

    def _zone(self, zone):
        try:
            return self.zones[zone]
        except KeyError:
            raise StorageError(f'unknown storage zone {zone!r}', op='zone', zone=zone,
                               code='storage_bad_request')

    def _url(self, zone, key):
        return self._zone(zone).base_url + quote(validate_key(key), safe='/')

    def _headers(self, zone):
        return {'AccessKey': self._zone(zone).access_key, 'Accept': '*/*'}

    def _timeout(self, timeout):
        if timeout is None:
            return (self.connect_timeout, self.read_timeout)
        if isinstance(timeout, tuple):
            return timeout
        return (self.connect_timeout, timeout)

    def _auth_hint(self, zone):
        """401 means a bad key OR the wrong region host, indistinguishably.

        Name both, or an operator will rotate a key that was always correct.
        """
        z = self._zone(zone)
        return (f"zone={z.zone_name!r} host={z.host!r} - a wrong region host returns 401 "
                f"exactly like a wrong access key, so check both "
                f"(known hosts: {', '.join(KNOWN_HOSTS)})")

    # -- operations ---------------------------------------------------

    def put(self, zone, key, data, *, content_type=None, timeout=None, logger=None,
            attempts=None):
        payload = _as_bytes(data)
        url = self._url(zone, key)
        headers = self._headers(zone)
        # Cheapest possible integrity guard: a truncated upload becomes a 400
        # instead of a silently corrupt artifact.
        headers['Checksum'] = hashlib.sha256(payload).hexdigest().upper()
        if content_type:
            headers['Content-Type'] = content_type
        request_timeout = self._timeout(timeout)

        def send():
            return self.session.put(url, data=payload, headers=headers,
                                    timeout=request_timeout)

        def classify(response):
            if response.status_code in (200, 201):
                return 'ok', len(payload)
            return self._classify_error(response, 'put', zone, key)

        call_with_retry(send, op='storage.put', attempts=attempts or self.attempts,
                        logger=logger, on_response=classify,
                        log_fields={'zone': zone, 'key': key, 'bytes': len(payload)})
        return len(payload)

    def get(self, zone, key, *, timeout=None, attempts=None, logger=None):
        url = self._url(zone, key)
        headers = self._headers(zone)
        request_timeout = self._timeout(timeout)

        def send():
            return self.session.get(url, headers=headers, timeout=request_timeout)

        def classify(response):
            if response.status_code == 200:
                return 'ok', response.content
            return self._classify_error(response, 'get', zone, key)

        return call_with_retry(send, op='storage.get', attempts=attempts or self.attempts,
                               logger=logger, on_response=classify,
                               log_fields={'zone': zone, 'key': key})

    def delete(self, zone, key, *, logger=None):
        url = self._url(zone, key)
        headers = self._headers(zone)

        def send():
            return self.session.delete(url, headers=headers, timeout=self._timeout(None))

        def classify(response):
            if response.status_code in (200, 204):
                return 'ok', True
            if response.status_code == 404:
                return 'ok', False  # already gone: idempotent, not an error
            return self._classify_error(response, 'delete', zone, key)

        return call_with_retry(send, op='storage.delete', attempts=self.attempts,
                               logger=logger, on_response=classify,
                               log_fields={'zone': zone, 'key': key})

    def stat(self, zone, key):
        """Size and mtime, via a listing of the parent directory.

        Bunny has no HEAD for objects, so this lists the containing folder. It
        is therefore not free - do not put it on a per-request path.
        """
        key = validate_key(key)
        prefix, _, name = key.rpartition('/')
        for entry in self.list(zone, prefix + '/' if prefix else ''):
            if entry['name'] == name:
                return {'bytes': entry['bytes'], 'last_modified': entry['last_modified']}
        return None

    def exists(self, zone, key):
        return self.stat(zone, key) is not None

    def list(self, zone, prefix):
        prefix = prefix or ''
        if prefix and not prefix.endswith('/'):
            prefix += '/'
        url = self._zone(zone).base_url + quote(prefix, safe='/')
        headers = self._headers(zone)

        def send():
            return self.session.get(url, headers=headers, timeout=self._timeout(None))

        def classify(response):
            if response.status_code == 200:
                return 'ok', response
            if response.status_code == 404:
                return 'ok', None  # empty directory
            return self._classify_error(response, 'list', zone, prefix)

        response = call_with_retry(send, op='storage.list', attempts=self.attempts,
                                   on_response=classify,
                                   log_fields={'zone': zone, 'key': prefix})
        if response is None:
            return []
        try:
            rows = response.json()
        except ValueError:
            return []

        entries = []
        for row in rows or []:
            if row.get('IsDirectory'):
                continue
            name = row.get('ObjectName') or ''
            entries.append({
                'name': name,
                'key': prefix + name,
                'bytes': int(row.get('Length') or 0),
                'last_modified': row.get('LastChanged') or row.get('DateCreated'),
            })
        return entries

    def public_url(self, zone, key):
        z = self._zone(zone)
        if not z.cdn_base_url:
            return None
        return f'{z.cdn_base_url}/{quote(validate_key(key), safe="/")}'

    def _classify_error(self, response, op, zone, key):
        status = response.status_code
        if status == 404:
            return 'fatal', StorageNotFound(f'{op}: not found: {key}', op=op,
                                            zone=zone, key=key, status=404)
        if status in (401, 403):
            return 'fatal', StorageError(
                f'{op}: HTTP {status} from Bunny - {self._auth_hint(zone)}',
                op=op, zone=zone, key=key, code='storage_auth', status=status)
        if status == 400:
            return 'fatal', StorageError(f'{op}: HTTP 400 (bad request or checksum mismatch)',
                                         op=op, zone=zone, key=key,
                                         code='storage_bad_request', status=400)
        if status in (429, 500, 502, 503, 504):
            return 'retry', StorageError(f'{op}: HTTP {status}', op=op, zone=zone, key=key,
                                         code='storage_unavailable', status=status,
                                         retryable=True)
        return 'fatal', StorageError(f'{op}: unexpected HTTP {status}', op=op, zone=zone,
                                     key=key, code='storage_unavailable', status=status)

    def describe(self):
        info = {'backend': 'bunny', 'zones': {}}
        for label, z in self.zones.items():
            info['zones'][label] = {
                'zone': z.zone_name,
                'host': z.host,
                'cdn_url': z.cdn_base_url,
                'access_key': 'set' if z.access_key else 'MISSING',
            }
        return info


class LocalBackend(StorageBackend):
    """Plain directories, for development. Keys mirror onto the tree verbatim
    so a developer can look at them."""
    name = 'local'

    def __init__(self, roots):
        self.roots = roots
        for path in roots.values():
            os.makedirs(path, exist_ok=True)

    def _path(self, zone, key):
        root = self.roots.get(zone)
        if root is None:
            raise StorageError(f'unknown storage zone {zone!r}', op='zone', zone=zone,
                               code='storage_bad_request')
        return os.path.join(root, *validate_key(key).split('/'))

    def put(self, zone, key, data, *, content_type=None, timeout=None, logger=None,
            attempts=None):
        payload = _as_bytes(data)
        path = self._path(zone, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # The one surviving temp-file + os.replace: a Bunny PUT is already
        # atomic, so this is the only place that needs to fake it.
        tmp = f'{path}.tmp-{uuid.uuid4().hex[:8]}'
        try:
            with open(tmp, 'wb') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise
        return len(payload)

    def get(self, zone, key, *, timeout=None, attempts=None, logger=None):
        path = self._path(zone, key)
        try:
            with open(path, 'rb') as handle:
                return handle.read()
        except FileNotFoundError:
            raise StorageNotFound(f'get: not found: {key}', op='get', zone=zone, key=key)

    def delete(self, zone, key, *, logger=None):
        path = self._path(zone, key)
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    def stat(self, zone, key):
        path = self._path(zone, key)
        try:
            st = os.stat(path)
        except OSError:
            return None
        return {'bytes': st.st_size, 'last_modified': st.st_mtime}

    def exists(self, zone, key):
        return os.path.exists(self._path(zone, key))

    def list(self, zone, prefix):
        prefix = (prefix or '').strip('/')
        root = self.roots.get(zone)
        if root is None:
            return []
        base = os.path.join(root, *prefix.split('/')) if prefix else root
        if not os.path.isdir(base):
            return []
        entries = []
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if not os.path.isfile(path) or '.tmp-' in name:
                continue
            st = os.stat(path)
            entries.append({'name': name,
                            'key': f'{prefix}/{name}' if prefix else name,
                            'bytes': st.st_size, 'last_modified': st.st_mtime})
        return entries

    def public_url(self, zone, key):
        return None  # makes /uploads/<file> fall through to send_from_directory

    def describe(self):
        return {'backend': 'local', 'roots': dict(self.roots)}


# ----------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------

REQUIRED_BUNNY_VARS = ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ZONE', 'BUNNY_PUBLIC_ACCESS_KEY',
                       'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY')
BUNNY_VAR_PREFIX = 'BUNNY_'


def _env(name, default=None):
    value = os.environ.get(name)
    value = value.strip().strip('"').strip("'") if value else ''
    return value or default


def build_backend():
    """Choose a backend from configuration. Never probes the filesystem."""
    present = [name for name in REQUIRED_BUNNY_VARS if _env(name)]

    if not present:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return LocalBackend({
            PUBLIC: _env('LOCAL_STORAGE_PUBLIC_DIR', os.path.join(repo, 'static', 'uploads')),
            PRIVATE: _env('LOCAL_STORAGE_PRIVATE_DIR', os.path.join(repo, 'uploads')),
        })

    missing = [name for name in REQUIRED_BUNNY_VARS if not _env(name)]
    if missing:
        # Deliberately fatal. Falling back to the container filesystem because
        # one variable was fat-fingered is precisely how a previous release
        # deleted customer files for weeks without anyone noticing.
        raise StorageError(
            'Bunny storage is partially configured - missing: ' + ', '.join(missing) +
            '. Set all of them, or none (to use local folders).',
            op='configure', code='storage_auth')

    host = _env('BUNNY_STORAGE_HOST')
    private_host = _env('BUNNY_STORAGE_HOST_PRIVATE', host)
    return BunnyBackend(
        {
            PUBLIC: BunnyZone(PUBLIC, _env('BUNNY_PUBLIC_ZONE'),
                              _env('BUNNY_PUBLIC_ACCESS_KEY'), host,
                              _env('BUNNY_PUBLIC_CDN_URL')),
            PRIVATE: BunnyZone(PRIVATE, _env('BUNNY_PRIVATE_ZONE'),
                               _env('BUNNY_PRIVATE_ACCESS_KEY'), private_host, None),
        },
        connect_timeout=float(_env('BUNNY_CONNECT_TIMEOUT', '5')),
        read_timeout=float(_env('BUNNY_READ_TIMEOUT', '30')),
        attempts=int(_env('BUNNY_ATTEMPTS', '3')),
    )


def get_storage(refresh=False):
    """Process-wide backend.

    A module singleton rather than app.config: the trainer and the background
    training thread run off the request thread and would otherwise need an app
    context just to reach storage.
    """
    global _backend
    if _backend is None or refresh:
        with _backend_lock:
            if _backend is None or refresh:
                _backend = build_backend()
    return _backend


def set_storage(backend):
    """Install a backend directly. For tests."""
    global _backend
    with _backend_lock:
        _backend = backend
    return _backend


def chat_read_timeout():
    """Read timeout for an artifact fetch on a visitor's chat request."""
    return float(_env('BUNNY_CHAT_READ_TIMEOUT', '8'))


def is_hosted():
    return bool(os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_ID')
                or os.environ.get('RAILWAY_ENVIRONMENT'))


def describe_storage():
    """Configuration snapshot for /health. No network calls, no secrets."""
    try:
        backend = get_storage()
    except StorageError as error:
        return {'backend': 'unconfigured', 'error': str(error)}
    info = backend.describe()
    info['hosted'] = is_hosted()
    info['warning'] = None
    if backend.name == 'local' and info['hosted']:
        info['warning'] = ('Running on a hosted instance with LOCAL file storage. '
                           'Uploaded documents, avatars and knowledge bases will be '
                           'DELETED on the next deploy. Configure the BUNNY_* variables.')
    return info


def check_storage():
    """Live round-trip probe of each zone. Opt-in - never on the health path."""
    backend = get_storage()
    results = {}
    for zone in ZONES:
        key = f'_healthcheck/{uuid.uuid4().hex}.txt'
        entry = {'ok': False, 'error': None}
        try:
            backend.put(zone, key, b'owlbee healthcheck', content_type='text/plain')
            entry['ok'] = backend.get(zone, key) == b'owlbee healthcheck'
        except Exception as error:
            entry['error'] = str(error)
        finally:
            try:
                backend.delete(zone, key)
            except Exception:
                pass
        results[zone] = entry
    return results


def log_storage_status():
    """One greppable boot line saying whether files will survive a deploy."""
    info = describe_storage()
    if info.get('backend') == 'bunny':
        zones = info.get('zones', {})
        public = zones.get(PUBLIC, {})
        private = zones.get(PRIVATE, {})
        print(f"[STORAGE] Bunny Edge Storage: public={public.get('zone')} "
              f"private={private.get('zone')} host={public.get('host')} "
              f"cdn={public.get('cdn_url') or 'none (avatars proxied)'}")
    elif info.get('backend') == 'local':
        roots = info.get('roots', {})
        print(f"[STORAGE] LOCAL FILESYSTEM: public={roots.get(PUBLIC)} "
              f"private={roots.get(PRIVATE)}")
    else:
        print(f"[STORAGE] NOT CONFIGURED: {info.get('error')}")
    if info.get('warning'):
        print(f"[STORAGE] WARNING: {info['warning']}")
    return info
