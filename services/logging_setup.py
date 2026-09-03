"""Structured logging for Owlbee.

One StreamHandler on stdout, JSON in production and human-readable locally.
The platform had no logging at all before this - only ~350 bare print() calls
with no levels, no timestamps and no way to correlate the lines of one training
run. Those prints stay (they already go to stdout, which is where this handler
writes); new code logs through here.

Usage:

    from services.logging_setup import get_logger, RunLogger

    log = RunLogger(get_logger('owlbee.training'),
                    run_id=run_id, chatbot_id=7, user_id=3)
    log.event('training.started', doc_count=3)

Privacy rule, and it is not negotiable: never log document text, knowledge-base
content, prompts, or visitor messages. Lengths, counts and ids only.
"""
import json
import logging
import os
import sys
from datetime import datetime

# Extras ride in one nested dict rather than as top-level `extra=` keys, because
# LogRecord already owns names like `message`, `module`, `name` and `args` -
# passing any of those through `extra=` raises inside logging itself.
_FIELD_KEY = 'owlbee'

_configured = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line: {"ts","level","logger","event","msg",...fields}."""

    def format(self, record):
        payload = {
            'ts': datetime.utcfromtimestamp(record.created).isoformat(timespec='milliseconds') + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        fields = getattr(record, _FIELD_KEY, None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            # A log line must never be the thing that breaks a training run.
            return json.dumps({'ts': payload['ts'], 'level': payload['level'],
                               'logger': payload['logger'], 'msg': payload['msg'],
                               'error': 'log serialization failed'})


class TextFormatter(logging.Formatter):
    """Readable single line for local development: LEVEL logger event k=v k=v."""

    def format(self, record):
        ts = datetime.utcfromtimestamp(record.created).strftime('%H:%M:%S')
        base = f"{ts} {record.levelname:<5} {record.name} {record.getMessage()}"
        fields = getattr(record, _FIELD_KEY, None)
        if isinstance(fields, dict):
            extras = ' '.join(f"{k}={v}" for k, v in fields.items() if k != 'event')
            if extras:
                base = f"{base} {extras}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging(app=None):
    """Install the root handler. Idempotent - safe to call from create_app twice.

    LOG_LEVEL   default INFO
    LOG_FORMAT  'json' | 'text'. Defaults to json on Render/Railway (their log
                viewers index structured fields) and text locally, where a
                developer has to read it.
    """
    global _configured
    if _configured:
        return
    _configured = True

    level_name = (os.environ.get('LOG_LEVEL') or 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)

    hosted = bool(os.environ.get('RENDER') or os.environ.get('RENDER_DISK_PATH')
                  or os.environ.get('RAILWAY_ENVIRONMENT'))
    fmt = (os.environ.get('LOG_FORMAT') or ('json' if hosted else 'text')).lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == 'json' else TextFormatter())

    root = logging.getLogger()
    # Drop handlers we installed on a previous call (reloader, test harness).
    for existing in list(root.handlers):
        if getattr(existing, '_owlbee', False):
            root.removeHandler(existing)
    handler._owlbee = True
    root.addHandler(handler)
    root.setLevel(level)

    # Third-party noise. httpx logs a line per OpenAI request at INFO, which
    # would double every retry we already log ourselves.
    for noisy in ('werkzeug', 'openai', 'httpx', 'httpcore', 'urllib3'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if app is not None:
        app.logger.setLevel(level)

    logging.getLogger('owlbee').info('logging configured',
                                     extra={_FIELD_KEY: {'event': 'logging.configured',
                                                         'format': fmt, 'level': level_name}})


def get_logger(name='owlbee'):
    return logging.getLogger(name)


class RunLogger:
    """Binds run_id / chatbot_id / user_id once so no call site can forget them.

    Every line for a training run carries the same run_id, which is also in the
    status JSON and in the artifact - so a user-reported failure maps to a log
    grep in one hop.
    """

    def __init__(self, logger, **bound):
        self._logger = logger
        self._bound = {k: v for k, v in bound.items() if v is not None}

    def bind(self, **fields):
        """A child logger with extra permanent fields (e.g. model_alias, once known)."""
        merged = dict(self._bound)
        merged.update({k: v for k, v in fields.items() if v is not None})
        return RunLogger(self._logger, **merged)

    def event(self, event, level=logging.INFO, exc_info=False, **fields):
        payload = dict(self._bound)
        payload.update(fields)
        payload['event'] = event
        self._logger.log(level, event, extra={_FIELD_KEY: payload}, exc_info=exc_info)

    def debug(self, event, **fields):
        self.event(event, level=logging.DEBUG, **fields)

    def warning(self, event, **fields):
        self.event(event, level=logging.WARNING, **fields)

    def error(self, event, exc_info=False, **fields):
        self.event(event, level=logging.ERROR, exc_info=exc_info, **fields)
