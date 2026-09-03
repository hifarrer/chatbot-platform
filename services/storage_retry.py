"""Retry policy for object-storage HTTP calls.

A deliberate sibling of services/openai_retry.py rather than a generalization of
it. That module classifies on `openai.*` exception classes resolved at import
and declares itself the single retry authority for the OpenAI clients; bolting a
strategy parameter onto it would blur exactly the thing it exists to be. This
one classifies on HTTP status codes and `requests` exception types.

Every storage operation is idempotent - the same PUT with the same bytes to the
same key, a DELETE of an already-missing key - which is what makes retrying safe
here at all.
"""
import random
import time

import requests

# The service was reachable and the request was fine; it just did not work yet.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Retrying these only burns time: the request itself is wrong.
FATAL_STATUS = {
    400: 'storage_bad_request',
    401: 'storage_auth',
    403: 'storage_auth',
    405: 'storage_bad_request',
    413: 'storage_too_large',
}

RETRYABLE_EXCEPTIONS = (requests.ConnectionError, requests.Timeout)


def retry_after_seconds(response, max_delay):
    """Honour a Retry-After header. The server's number beats our guess."""
    if response is None:
        return None
    try:
        raw = response.headers.get('Retry-After')
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return max(0.0, min(float(raw), max_delay))
    except (TypeError, ValueError):
        return None  # HTTP-date form; fall back to computed backoff


def call_with_retry(fn, *, op, attempts=3, base_delay=0.4, max_delay=4.0,
                    deadline=None, logger=None, log_fields=None,
                    on_response=None):
    """Run `fn()` -> requests.Response, retrying transient failures.

    `fn` must perform exactly one HTTP request and return the Response.
    `on_response(response)` classifies it and returns:
        ('ok', value)      -> return value to the caller
        ('retry', None)    -> transient; back off and try again
        ('fatal', error)   -> raise error immediately
    Leaving on_response unset falls back to the status tables above.

    Raises the last error once attempts are exhausted, or immediately on a fatal
    classification. Non-HTTP exceptions propagate untouched - a bug in our own
    encoding is not a network blip.
    """
    from services.object_storage import StorageError

    fields = dict(log_fields or {})
    last_error = None

    for attempt in range(1, attempts + 1):
        response = None
        try:
            response = fn()
        except RETRYABLE_EXCEPTIONS as error:
            last_error = StorageError(f"{op}: {type(error).__name__}: {error}",
                                      op=op, code='storage_unavailable',
                                      attempts=attempt, retryable=True,
                                      **{k: fields.get(k) for k in ('key', 'zone')})
        else:
            verdict, payload = (on_response(response) if on_response
                                else _classify(response, op, attempt, fields))
            if verdict == 'ok':
                return payload
            if verdict == 'fatal':
                if logger:
                    logger.event('storage.fatal', op=op, attempt=attempt,
                                 status=getattr(response, 'status_code', None), **fields)
                raise payload
            last_error = payload

        if attempt >= attempts:
            break

        delay = min(max_delay, base_delay * (2 ** (attempt - 1))) * random.uniform(0.5, 1.5)
        server_delay = retry_after_seconds(response, max_delay)
        if server_delay is not None:
            delay = server_delay

        if deadline is not None and (time.monotonic() + delay) >= deadline:
            if logger:
                logger.event('storage.deadline', op=op, attempt=attempt, **fields)
            break

        if logger:
            logger.event('storage.retry', op=op, attempt=attempt, attempts=attempts,
                         status=getattr(response, 'status_code', None),
                         delay_ms=int(delay * 1000), **fields)
        time.sleep(delay)

    if logger:
        logger.event('storage.exhausted', op=op, attempts=attempts, **fields)
    if last_error is not None:
        raise last_error
    raise StorageError(f"{op}: failed after {attempts} attempt(s)", op=op,
                       code='storage_unavailable', attempts=attempts, retryable=True)


def _classify(response, op, attempt, fields):
    """Default status classification. Returns (verdict, payload)."""
    from services.object_storage import StorageError

    status = response.status_code
    if status in FATAL_STATUS:
        code = FATAL_STATUS[status]
        return 'fatal', StorageError(
            f"{op}: HTTP {status}", op=op, code=code, status=status,
            attempts=attempt, retryable=False,
            zone=fields.get('zone'), key=fields.get('key'))
    if status in RETRYABLE_STATUS:
        return 'retry', StorageError(
            f"{op}: HTTP {status}", op=op, code='storage_unavailable', status=status,
            attempts=attempt, retryable=True,
            zone=fields.get('zone'), key=fields.get('key'))
    return 'ok', response
