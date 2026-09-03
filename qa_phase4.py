#!/usr/bin/env python3
"""Phase 4 QA: Bunny.net object storage.

    python qa_phase4.py           # offline: stubbed HTTP + fake backend, no network
    python qa_phase4.py --live    # + real round trips against the configured zones

Offline needs no credentials and costs nothing, so it runs anywhere. --live
needs the BUNNY_* variables and writes only `_qa_`-prefixed keys, cleaned up in
a finally block so a crash leaves a sweepable mess rather than an anonymous one.
"""
import argparse
import hashlib
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --live reads the BUNNY_* credentials from .env, the same file the app uses.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

RESULTS = []


def check(name, passed, detail=''):
    RESULTS.append((name, bool(passed), detail))
    print(('  PASS  ' if passed else '  FAIL  ') + name + (f'  [{detail}]' if detail else ''))
    return passed


def banner(title):
    print('\n' + '=' * 72)
    print(title)
    print('=' * 72)


# ----------------------------------------------------------------------
# Stubs
# ----------------------------------------------------------------------

class StubResponse:
    def __init__(self, status_code, content=b'', headers=None, json_data=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError('no json')
        return self._json


class StubSession:
    """Records every request and replays a scripted sequence of responses."""

    def __init__(self, script):
        self.script = list(script)      # list of StubResponse, or callables
        self.calls = []                 # (method, url, headers, body_len)

    def _next(self, method, url, headers, data):
        self.calls.append({'method': method, 'url': url, 'headers': dict(headers or {}),
                           'bytes': len(data) if data is not None else 0})
        if not self.script:
            raise AssertionError('StubSession ran out of scripted responses')
        item = self.script.pop(0)
        if callable(item):
            return item()
        return item

    def put(self, url, data=None, headers=None, timeout=None):
        return self._next('PUT', url, headers, data)

    def get(self, url, headers=None, timeout=None):
        return self._next('GET', url, headers, None)

    def delete(self, url, headers=None, timeout=None):
        return self._next('DELETE', url, headers, None)


def bunny_backend(script, attempts=3):
    import services.object_storage as st
    session = StubSession(script)
    backend = st.BunnyBackend(
        {st.PUBLIC: st.BunnyZone(st.PUBLIC, 'owlbee-public', 'pub-key',
                                 'storage.bunnycdn.com', 'https://cdn.example.net'),
         st.PRIVATE: st.BunnyZone(st.PRIVATE, 'owlbee-private', 'priv-key',
                                  'storage.bunnycdn.com', None)},
        attempts=attempts, session=session)
    return backend, session


class FakeBackend:
    """In-memory backend with fault injection and a call counter."""
    name = 'fake'

    def __init__(self, cdn_url='https://cdn.example.net'):
        self.objects = {'public': {}, 'private': {}}
        self.calls = {'put': 0, 'get': 0, 'delete': 0, 'list': 0, 'stat': 0}
        self.fail_next_put = None       # an exception to raise
        self.fail_next_get = None
        self.cdn_url = cdn_url

    def put(self, zone, key, data, *, content_type=None, timeout=None, logger=None,
            attempts=None):
        self.calls['put'] += 1
        if self.fail_next_put is not None:
            error, self.fail_next_put = self.fail_next_put, None
            raise error
        payload = data if isinstance(data, bytes) else (
            data.encode('utf-8') if isinstance(data, str) else data.read())
        self.objects[zone][key] = payload
        return len(payload)

    def get(self, zone, key, *, timeout=None, attempts=None, logger=None):
        self.calls['get'] += 1
        if self.fail_next_get is not None:
            error, self.fail_next_get = self.fail_next_get, None
            raise error
        import services.object_storage as st
        try:
            return self.objects[zone][key]
        except KeyError:
            raise st.StorageNotFound(f'get: not found: {key}', op='get', zone=zone, key=key)

    def delete(self, zone, key, *, logger=None):
        self.calls['delete'] += 1
        return self.objects[zone].pop(key, None) is not None

    def exists(self, zone, key):
        return key in self.objects[zone]

    def stat(self, zone, key):
        self.calls['stat'] += 1
        blob = self.objects[zone].get(key)
        return None if blob is None else {'bytes': len(blob), 'last_modified': None}

    def list(self, zone, prefix):
        self.calls['list'] += 1
        prefix = prefix or ''
        return [{'name': k.rsplit('/', 1)[-1], 'key': k, 'bytes': len(v),
                 'last_modified': None}
                for k, v in sorted(self.objects[zone].items()) if k.startswith(prefix)]

    def public_url(self, zone, key):
        if zone == 'public' and self.cdn_url:
            return f'{self.cdn_url}/{key}'
        return None

    def describe(self):
        return {'backend': 'fake'}


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

def test_keys():
    banner('Key builders and traversal validation')
    import services.object_storage as st

    backslash = chr(92)
    malicious = ['../etc/passwd', '/abs/path', 'a' + backslash + 'b', 'a//b', 'x/../y',
                 '', 'a/./b', 'a' + chr(8) + 'b', 'a' + chr(0) + 'b', 'a' + chr(127)]
    accepted = []
    for key in malicious:
        try:
            st.validate_key(key)
            accepted.append(key)
        except (ValueError, TypeError):
            pass
    check('traversal and control-character keys are rejected', not accepted, repr(accepted))
    check('ordinary keys pass', st.validate_key('documents/7/uuid_My File.pdf') is not None)
    check('document_key shards by chatbot', st.document_key(7, 'u_f.pdf') == 'documents/7/u_f.pdf')
    check('avatar_key stays flat and keeps the filename',
          st.avatar_key('avatar_bot_20260101.png') == 'avatars/avatar_bot_20260101.png')
    check('artifact_key matches the chatbot id', st.artifact_key(42) == 'training/chatbot_42.json')
    # A crafted filename reaching avatar_key must not escape the prefix.
    try:
        st.avatar_key('../training/chatbot_1.json')
        check('avatar_key rejects traversal', False, 'accepted')
    except ValueError:
        check('avatar_key rejects traversal', True)


def test_local_backend():
    banner('Local backend')
    import services.object_storage as st

    root = tempfile.mkdtemp(prefix='owlbee_local_')
    backend = st.LocalBackend({st.PUBLIC: os.path.join(root, 'pub'),
                               st.PRIVATE: os.path.join(root, 'priv')})

    backend.put(st.PRIVATE, 'training/chatbot_1.json', b'{"a":1}')
    check('round trip', backend.get(st.PRIVATE, 'training/chatbot_1.json') == b'{"a":1}')
    check('stat reports size', backend.stat(st.PRIVATE, 'training/chatbot_1.json')['bytes'] == 7)
    check('list finds the object',
          [e['key'] for e in backend.list(st.PRIVATE, 'training/')] == ['training/chatbot_1.json'])
    check('delete returns True then False',
          backend.delete(st.PRIVATE, 'training/chatbot_1.json') is True
          and backend.delete(st.PRIVATE, 'training/chatbot_1.json') is False)
    try:
        backend.get(st.PRIVATE, 'training/chatbot_1.json')
        check('missing get raises StorageNotFound', False, 'no exception')
    except st.StorageNotFound:
        check('missing get raises StorageNotFound', True)
    leftovers = [f for f in os.listdir(os.path.join(root, 'priv', 'training')) if '.tmp-' in f]
    check('atomic write leaves no temp files', not leftovers, str(leftovers))
    check('local backend has no public URL (falls through to send_from_directory)',
          backend.public_url(st.PUBLIC, 'avatars/a.png') is None)


def test_bunny_protocol():
    banner('Bunny HTTP protocol')
    import services.object_storage as st

    payload = b'hello owlbee'
    backend, session = bunny_backend([StubResponse(201)])
    backend.put(st.PRIVATE, 'training/chatbot_1.json', payload,
                content_type='application/json')
    call = session.calls[0]
    check('PUT goes to the zone URL',
          call['url'] == 'https://storage.bunnycdn.com/owlbee-private/training/chatbot_1.json',
          call['url'])
    check('PUT sends the AccessKey header', call['headers'].get('AccessKey') == 'priv-key')
    check('PUT sends an uppercase SHA256 Checksum',
          call['headers'].get('Checksum') == hashlib.sha256(payload).hexdigest().upper(),
          str(call['headers'].get('Checksum'))[:16])
    check('PUT sends Content-Type', call['headers'].get('Content-Type') == 'application/json')

    backend, _ = bunny_backend([StubResponse(200, content=b'body')])
    check('GET returns bytes', backend.get(st.PRIVATE, 'training/x.json') == b'body')

    backend, _ = bunny_backend([StubResponse(404)])
    try:
        backend.get(st.PRIVATE, 'nope.json')
        check('GET 404 raises StorageNotFound', False, 'no exception')
    except st.StorageNotFound:
        check('GET 404 raises StorageNotFound', True)

    backend, session = bunny_backend([StubResponse(404)])
    check('DELETE 404 is idempotent, not an error',
          backend.delete(st.PRIVATE, 'gone.json') is False)

    backend, _ = bunny_backend([StubResponse(200, json_data=[
        {'ObjectName': 'chatbot_1.json', 'Length': 12, 'IsDirectory': False,
         'LastChanged': '2026-08-30T00:00:00'},
        {'ObjectName': 'sub', 'Length': 0, 'IsDirectory': True},
    ])])
    listing = backend.list(st.PRIVATE, 'training/')
    check('list parses files and skips directories',
          [e['key'] for e in listing] == ['training/chatbot_1.json'], str(listing))

    check('public zone builds a CDN URL',
          bunny_backend([])[0].public_url(st.PUBLIC, 'avatars/a.png')
          == 'https://cdn.example.net/avatars/a.png')
    check('private zone has no public URL',
          bunny_backend([])[0].public_url(st.PRIVATE, 'documents/1/x.pdf') is None)


def test_bunny_failures():
    banner('Bunny error classification and retries')
    import services.object_storage as st

    # 401 is fatal, tried once, and names the host (a wrong region looks identical)
    backend, session = bunny_backend([StubResponse(401)])
    try:
        backend.put(st.PRIVATE, 'x.json', b'x')
        check('401 is fatal', False, 'no exception')
    except st.StorageError as error:
        check('401 is fatal with a single attempt', len(session.calls) == 1,
              f'{len(session.calls)} calls')
        check('401 error names the host and the zone',
              'storage.bunnycdn.com' in str(error) and 'owlbee-private' in str(error),
              str(error)[:80])
        check('401 maps to storage_auth', error.code == 'storage_auth', error.code)

    # 500 is retried up to the attempt limit, then raises
    backend, session = bunny_backend([StubResponse(500), StubResponse(500),
                                      StubResponse(500)], attempts=3)
    try:
        backend.put(st.PRIVATE, 'x.json', b'x')
        check('persistent 5xx raises', False, 'no exception')
    except st.StorageError as error:
        check('5xx retried to the attempt limit', len(session.calls) == 3,
              f'{len(session.calls)} calls')
        check('exhausted 5xx maps to storage_unavailable',
              error.code == 'storage_unavailable', error.code)

    # transient then success
    backend, session = bunny_backend([StubResponse(503), StubResponse(201)], attempts=3)
    backend.put(st.PRIVATE, 'x.json', b'x')
    check('transient 5xx then success', len(session.calls) == 2, f'{len(session.calls)} calls')

    # 400 (checksum mismatch / bad request) is fatal
    backend, session = bunny_backend([StubResponse(400)])
    try:
        backend.put(st.PRIVATE, 'x.json', b'x')
        check('400 is fatal', False, 'no exception')
    except st.StorageError as error:
        check('400 is fatal and not retried',
              error.code == 'storage_bad_request' and len(session.calls) == 1, error.code)

    # connection errors are retried
    import requests as rq
    def boom():
        raise rq.ConnectionError('refused')
    backend, session = bunny_backend([boom, boom, StubResponse(201)], attempts=3)
    backend.put(st.PRIVATE, 'x.json', b'x')
    check('connection errors are retried', len(session.calls) == 3, f'{len(session.calls)} calls')

    # Retry-After is honoured over the computed backoff
    backend, session = bunny_backend(
        [StubResponse(429, headers={'Retry-After': '0.01'}), StubResponse(201)], attempts=2)
    started = time.monotonic()
    backend.put(st.PRIVATE, 'x.json', b'x')
    check('429 honours Retry-After', (time.monotonic() - started) < 1.0,
          f'{time.monotonic() - started:.2f}s')


def test_configuration():
    banner('Backend selection')
    import importlib
    import services.object_storage as st

    saved = {k: os.environ.get(k) for k in list(os.environ) if k.startswith('BUNNY_')}
    try:
        for key in list(os.environ):
            if key.startswith('BUNNY_'):
                os.environ.pop(key)
        importlib.reload(st)
        check('no BUNNY_ vars gives the local backend', st.build_backend().name == 'local')

        os.environ['BUNNY_PUBLIC_ZONE'] = 'owlbee-public'
        try:
            st.build_backend()
            check('partial configuration is fatal', False, 'no exception')
        except st.StorageError as error:
            missing_named = all(name in str(error) for name in
                                ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ACCESS_KEY',
                                 'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY'))
            check('partial configuration is fatal and names every missing var',
                  missing_named, str(error)[:110])

        os.environ.update({'BUNNY_STORAGE_HOST': 'ny.storage.bunnycdn.com',
                           'BUNNY_PUBLIC_ACCESS_KEY': 'pub',
                           'BUNNY_PRIVATE_ZONE': 'owlbee-private',
                           'BUNNY_PRIVATE_ACCESS_KEY': 'priv',
                           'BUNNY_PUBLIC_CDN_URL': 'https://cdn.example.net/'})
        backend = st.build_backend()
        check('full configuration gives the Bunny backend', backend.name == 'bunny')
        check('region host is used', backend.zones[st.PUBLIC].host == 'ny.storage.bunnycdn.com')
        check('trailing slash is stripped from the CDN URL',
              backend.zones[st.PUBLIC].cdn_base_url == 'https://cdn.example.net')
        check('private zone gets no CDN URL',
              backend.zones[st.PRIVATE].cdn_base_url is None)
    finally:
        for key in list(os.environ):
            if key.startswith('BUNNY_'):
                os.environ.pop(key)
        os.environ.update({k: v for k, v in saved.items() if v is not None})
        importlib.reload(st)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true',
                        help='also run real round trips against the configured zones')
    args = parser.parse_args()

    test_keys()
    test_local_backend()
    test_bunny_protocol()
    test_bunny_failures()
    test_configuration()

    if args.live:
        from qa_phase4_live import run_live_tests
        run_live_tests(check, banner)

    banner('SUMMARY')
    failed = [name for name, passed, _d in RESULTS if not passed]
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed')
    for name in failed:
        print(f'  FAILED: {name}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
