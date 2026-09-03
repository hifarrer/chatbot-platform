"""Live Bunny.net checks. Invoked by `python qa_phase4.py --live`.

Every object uses a `_qa_` key prefix and is removed in a finally block, so a
crash leaves a sweepable mess rather than an anonymous one.
"""
import os
import statistics
import time
import uuid

import requests


def run_live_tests(check, banner):
    import services.object_storage as st

    banner('Live: zone reachability')

    try:
        backend = st.get_storage(refresh=True)
    except st.StorageError as error:
        check('storage configuration is valid', False, str(error)[:110])
        return
    if backend.name != 'bunny':
        check('Bunny backend is configured', False,
              'BUNNY_* variables are not set; nothing to test live')
        return
    check('Bunny backend is configured', True, backend.describe()['zones'][st.PUBLIC]['host'])

    tag = uuid.uuid4().hex[:10]
    payload = b'owlbee live check ' + tag.encode()
    created = []

    try:
        for zone in (st.PUBLIC, st.PRIVATE):
            key = f'_qa_/{tag}.txt'
            try:
                backend.put(zone, key, payload, content_type='text/plain')
                created.append((zone, key))
                check(f'{zone}: upload and download round trip',
                      backend.get(zone, key) == payload)
                info = backend.stat(zone, key)
                check(f'{zone}: stat reports the right size',
                      info and info['bytes'] == len(payload), str(info))
            except st.StorageError as error:
                check(f'{zone}: upload and download round trip', False, str(error)[:110])

        # ---- the wrong-region trap -------------------------------------
        banner('Live: wrong region host')
        wrong_host = next(h for h in st.KNOWN_HOSTS
                          if h != backend.zones[st.PRIVATE].host)
        z = backend.zones[st.PRIVATE]
        wrong = st.BunnyBackend(
            {st.PRIVATE: st.BunnyZone(st.PRIVATE, z.zone_name, z.access_key, wrong_host)},
            attempts=1)
        try:
            wrong.put(st.PRIVATE, f'_qa_/{tag}_wrong.txt', b'x')
            check('a wrong region host is rejected', False, 'the upload succeeded')
        except st.StorageError as error:
            check('a wrong region host is rejected', error.code == 'storage_auth', error.code)
            check('the error names the host, since 401 also means a bad key',
                  wrong_host in str(error), str(error)[:100])

        # ---- privacy, in both directions --------------------------------
        banner('Live: zone privacy')
        cdn = backend.zones[st.PUBLIC].cdn_base_url
        public_key = f'_qa_/{tag}.txt'
        if cdn:
            url = f'{cdn}/{public_key}'
            try:
                # A pull zone can take a moment to serve a brand-new object.
                got = None
                for _attempt in range(3):
                    response = requests.get(url, timeout=15)
                    if response.status_code == 200:
                        got = response.content
                        break
                    time.sleep(2)
                check('the public zone is readable through the CDN with no access key',
                      got == payload, f'{url} -> {got is not None}')
            except requests.RequestException as error:
                check('the public zone is readable through the CDN with no access key',
                      False, str(error)[:90])
        else:
            check('public CDN URL configured', False,
                  'BUNNY_PUBLIC_CDN_URL is unset, so avatars will be proxied by Flask')

        private_url = backend.zones[st.PRIVATE].base_url + f'_qa_/{tag}.txt'
        try:
            response = requests.get(private_url, timeout=15)
            # This is the check that keeps customer documents from being
            # world-readable: no access key must mean no access.
            check('the private zone refuses anonymous reads',
                  response.status_code in (401, 403), f'HTTP {response.status_code}')
        except requests.RequestException as error:
            check('the private zone refuses anonymous reads', False, str(error)[:90])

        # ---- cache-miss budget ------------------------------------------
        banner('Live: artifact fetch budget')
        big_key = f'_qa_/{tag}_artifact.json'
        blob = b'{"pad":"' + b'x' * (4 * 1024 * 1024) + b'"}'
        try:
            backend.put(st.PRIVATE, big_key, blob, content_type='application/json')
            created.append((st.PRIVATE, big_key))
            timings = []
            for _ in range(3):
                started = time.monotonic()
                backend.get(st.PRIVATE, big_key)
                timings.append((time.monotonic() - started) * 1000)
            median = statistics.median(timings)
            check('a 4MB artifact fetch completes', True, f'median {median:.0f} ms')
            # Not a hard failure from a dev machine - the number that matters is
            # measured from the Render region - but a useful smoke signal.
            check('artifact fetch is within the chat cache-miss budget',
                  median < 8000, f'median {median:.0f} ms vs 8000 ms timeout')
        except st.StorageError as error:
            check('a 4MB artifact fetch completes', False, str(error)[:110])

    finally:
        for zone, key in created:
            try:
                backend.delete(zone, key)
            except Exception:
                print(f'  (could not clean up {zone}:{key})')
        try:
            backend.delete(st.PRIVATE, f'_qa_/{tag}_wrong.txt')
        except Exception:
            pass
