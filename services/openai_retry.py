"""Retry/backoff for OpenAI calls.

Before this, a single rate-limit blip or connection reset during training was
enough to silently degrade a chatbot: the caller swallowed the exception and
fell through to a broken fallback while reporting success. Retrying the calls
that are worth retrying - and refusing to retry the ones that aren't - is half
the fix; the other half is that failures now propagate (services/training_errors.py).

This module is the *single* retry authority. Both OpenAI() clients are built
with max_retries=0 for exactly that reason: leaving the SDK's own max_retries=2
in place would turn 4 attempts here into 12 real API calls.
"""
import random
import time

import openai


def _exc(name):
    """Resolve an openai exception class defensively.

    The class set shifts between SDK 1.x and 2.x point releases, and the repo
    currently has a pin/venv mismatch. A missing name must degrade to "not
    classified", never to an ImportError at boot.
    """
    return getattr(openai, name, None)


def _classes(*names):
    return tuple(c for c in (_exc(n) for n in names) if isinstance(c, type))


# Worth another attempt: the request was fine, the service wasn't.
RETRYABLE = _classes('RateLimitError', 'APITimeoutError',
                     'APIConnectionError', 'InternalServerError')

# Retrying these just burns time and money - the request itself is wrong.
FATAL = _classes('AuthenticationError', 'PermissionDeniedError', 'BadRequestError',
                 'NotFoundError', 'UnprocessableEntityError')

# Exception class name -> our stable error_code (services/training_errors.py).
FATAL_CODES = {
    'AuthenticationError': 'openai_auth',
    'PermissionDeniedError': 'openai_forbidden',
    'BadRequestError': 'openai_bad_request',
    'NotFoundError': 'openai_model_missing',
    'UnprocessableEntityError': 'openai_bad_request',
}


class OpenAICallFailed(Exception):
    """An OpenAI call that will not be retried again - fatal, or out of attempts."""

    def __init__(self, message, *, code, op, attempts, retryable, last_error=None):
        super().__init__(message)
        self.code = code
        self.op = op
        self.attempts = attempts
        self.retryable = retryable
        self.last_error = last_error


def _retry_after_seconds(error):
    """Honour a Retry-After header when the service sends one.

    Our computed backoff is a guess; the server's number is not.
    """
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', None)
    if not headers:
        return None
    for key, scale in (('retry-after-ms', 0.001), ('retry-after', 1.0)):
        raw = None
        try:
            raw = headers.get(key)
        except Exception:
            continue
        if raw is None:
            continue
        try:
            return max(0.0, float(raw) * scale)
        except (TypeError, ValueError):
            continue  # HTTP-date form; fall back to our own backoff
    return None


def _status_code(error):
    return getattr(error, 'status_code', None) or getattr(error, 'code', None)


def call_with_retry(fn, *, op, attempts=4, base_delay=1.0, max_delay=20.0,
                    deadline=None, logger=None, log_fields=None, counter=None):
    """Run `fn()` (exactly one API call, no arguments) with jittered exponential backoff.

    Returns whatever fn() returns.

    Raises OpenAICallFailed on a fatal error (immediately, no retries) or once
    attempts are exhausted. Anything not classified as retryable or fatal
    propagates unchanged - a JSONDecodeError on our side is a bug in our parsing,
    not a network blip, and hiding it behind a retry would be the old mistake in
    a new place.

    deadline: an absolute time.monotonic() value. Before sleeping, if the sleep
        would run past it, give up now with 'openai_timeout'. The training runner
        passes the run's remaining budget, so no run can hang forever.
    counter: a mutable dict; counter['attempts'] accumulates every attempt made
        across every call in a run, for TrainingRun.api_attempts.
    """
    fields = dict(log_fields or {})
    last_error = None

    for attempt in range(1, attempts + 1):
        if counter is not None:
            counter['attempts'] = counter.get('attempts', 0) + 1
        try:
            return fn()
        except Exception as error:
            error_name = type(error).__name__

            if FATAL and isinstance(error, FATAL):
                code = FATAL_CODES.get(error_name, 'openai_bad_request')
                if logger:
                    logger.event('openai.fatal', op=op, attempt=attempt,
                                 error_type=error_name, status_code=_status_code(error),
                                 **fields)
                raise OpenAICallFailed(f"{op}: {error_name}: {error}", code=code, op=op,
                                       attempts=attempt, retryable=False,
                                       last_error=error) from error

            if not (RETRYABLE and isinstance(error, RETRYABLE)):
                raise  # not ours to classify - let the real bug surface

            last_error = error
            if attempt >= attempts:
                break

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= random.uniform(0.5, 1.5)
            server_delay = _retry_after_seconds(error)
            if server_delay is not None:
                delay = min(max_delay, server_delay)

            if deadline is not None and (time.monotonic() + delay) >= deadline:
                if logger:
                    logger.event('openai.deadline', op=op, attempt=attempt,
                                 error_type=error_name, **fields)
                raise OpenAICallFailed(
                    f"{op}: out of time after {attempt} attempt(s): {error_name}: {error}",
                    code='openai_timeout', op=op, attempts=attempt, retryable=True,
                    last_error=error) from error

            if logger:
                logger.event('openai.retry', op=op, attempt=attempt, attempts=attempts,
                             error_type=error_name, status_code=_status_code(error),
                             delay_ms=int(delay * 1000), **fields)
            time.sleep(delay)

    error_name = type(last_error).__name__ if last_error else 'Unknown'
    if logger:
        logger.event('openai.exhausted', op=op, attempts=attempts,
                     error_type=error_name, **fields)
    raise OpenAICallFailed(
        f"{op}: gave up after {attempts} attempts: {error_name}: {last_error}",
        code='openai_unavailable', op=op, attempts=attempts, retryable=True,
        last_error=last_error)
