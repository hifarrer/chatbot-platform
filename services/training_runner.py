"""Run chatbot training off the request thread.

Training used to run inline in POST /train_chatbot. On Render that meant one
gunicorn worker with a 120 s timeout doing document parsing plus an unbounded
OpenAI call: long runs died with a 502 mid-flight, and while one ran, every
embedded chat widget on every customer site was blocked behind it.

Now the request enqueues a TrainingRun row, hands the work to a daemon thread,
and returns 202. The row - not the thread - is the source of truth, so a user
can close the tab, and a restart that kills the thread is detectable rather than
looking like a run that is still going.

Deliberately no Redis, no Celery, no second Render service: one instance, a
thread, and a table the UI can poll.
"""
import os
import socket
import threading
import time
from datetime import datetime, timedelta

from services.logging_setup import RunLogger, get_logger
from services.training_errors import TrainingError, friendly_error

HEARTBEAT_SECONDS = 15
# Comfortably longer than the worst case for a single knowledge-base call
# (4 attempts x 180 s + backoff), so a slow-but-alive run is never reaped.
STALE_AFTER_SECONDS = 900
MAX_CONCURRENT_RUNS = 2
REAP_THROTTLE_SECONDS = 60
RUN_DEADLINE_SECONDS = int(os.environ.get('TRAINING_RUN_DEADLINE', 1800))

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_reap_lock = threading.Lock()
_last_reap = 0.0

_log = get_logger('owlbee.training')


def host_id():
    """Identifies this process, so a boot-time reaper knows which rows it owns."""
    try:
        name = socket.gethostname()
    except Exception:
        name = 'unknown'
    return f"{name}:{os.getpid()}"[:64]


def _utcnow():
    return datetime.utcnow()


# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------

def active_run_for_chatbot(chatbot_id):
    from app import TrainingRun
    return (TrainingRun.query
            .filter(TrainingRun.chatbot_id == chatbot_id,
                    TrainingRun.status.in_(('queued', 'running')))
            .order_by(TrainingRun.created_at.desc())
            .first())


def latest_run_for_chatbot(chatbot_id):
    from app import TrainingRun
    return (TrainingRun.query
            .filter(TrainingRun.chatbot_id == chatbot_id)
            .order_by(TrainingRun.created_at.desc())
            .first())


def get_run(chatbot_id, run_id):
    from app import TrainingRun
    return TrainingRun.query.filter_by(chatbot_id=chatbot_id, run_id=run_id).first()


def run_to_dict(run):
    """The status endpoint's JSON contract."""
    from app import TRAINING_TERMINAL_STATUSES

    if run is None:
        return None

    def iso(value):
        return value.isoformat(timespec='seconds') + 'Z' if value else None

    reference = run.finished_at or _utcnow()
    elapsed = None
    if run.started_at:
        elapsed = max(0, int((reference - run.started_at).total_seconds()))

    return {
        'run_id': run.run_id,
        'status': run.status,
        'phase': run.phase,
        'progress': int(run.progress or 0),
        'message': run.message,
        'error_code': run.error_code,
        'error_message': run.error_message,
        # The sentence the user reads. The raw error_message goes behind a
        # <details> for support; never show it as the primary message.
        'friendly_error': friendly_error(run.error_code) if run.error_code else None,
        'model_alias': run.model_alias,
        'doc_count': run.doc_count,
        'char_count': run.char_count,
        'chunk_count': run.chunk_count,
        'total_tokens': int(run.total_tokens or 0),
        'embedding_tokens': int(run.embedding_tokens or 0),
        'created_at': iso(run.created_at),
        'started_at': iso(run.started_at),
        'finished_at': iso(run.finished_at),
        'elapsed_seconds': elapsed,
        'terminal': run.status in TRAINING_TERMINAL_STATUSES,
    }


# ----------------------------------------------------------------------
# Enqueue
# ----------------------------------------------------------------------

def enqueue_training(app, chatbot_id, user_id):
    """Create a run row and start its worker. Returns (run, created).

    created=False means a run was already in flight; the caller answers 409 and
    the browser attaches to that run instead of starting a duplicate.
    """
    import uuid
    from app import db, TrainingRun

    existing = active_run_for_chatbot(chatbot_id)
    if existing is not None:
        return existing, False

    run = TrainingRun(
        run_id=uuid.uuid4().hex,
        chatbot_id=chatbot_id,
        user_id=user_id,
        status='queued',
        phase='queued',
        progress=0,
        message='Waiting to start...',
        host=host_id(),
        created_at=_utcnow(),
    )
    db.session.add(run)
    db.session.commit()

    log = RunLogger(_log, run_id=run.run_id, chatbot_id=chatbot_id, user_id=user_id)
    log.event('training.enqueued')

    # Only ids cross the thread boundary. Passing the ORM instance would hand a
    # second thread an object bound to the request's session - the classic route
    # to DetachedInstanceError and cross-session corruption.
    thread = threading.Thread(target=_worker, args=(app, run.id, run.run_id),
                              name=f'train-{run.run_id[:8]}', daemon=True)
    thread.start()
    return run, True


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------

def _worker(app, run_pk, run_id):
    """Thread entry point. Owns its own app context, session and semaphore slot."""
    acquired = _slots.acquire(timeout=RUN_DEADLINE_SECONDS)
    with app.app_context():
        from app import db
        try:
            if not acquired:
                _fail_run(run_pk, 'internal', 'training queue is full; please try again')
                return
            _execute(app, run_pk, run_id)
        except BaseException as error:  # noqa: BLE001 - the thread must not die silently
            _fail_run(run_pk, getattr(error, 'code', 'internal'), str(error))
        finally:
            if acquired:
                _slots.release()
            # Mandatory: returns the pooled connection. Context teardown would
            # normally do it, but a BaseException path can skip that.
            try:
                db.session.remove()
            except Exception:
                pass


def _fail_run(run_pk, code, detail, phase=None):
    """Record a failure on a session that may already be dirty from the failure."""
    from app import db, TrainingRun
    try:
        db.session.rollback()
        run = db.session.get(TrainingRun, run_pk)
        if run is None or run.status in ('cancelled',):
            return
        run.status = 'failed'
        run.error_code = code or 'internal'
        run.error_message = (detail or '')[:4000]
        run.phase = phase or run.phase
        run.finished_at = _utcnow()
        run.heartbeat_at = _utcnow()
        db.session.commit()
        RunLogger(_log, run_id=run.run_id, chatbot_id=run.chatbot_id).error(
            'training.failed', error_code=run.error_code,
            error_message=run.error_message[:300], phase=run.phase)
    except Exception as error:
        # Give up on bookkeeping; the reaper collects the row by heartbeat age.
        _log.error(f'could not record training failure for run {run_pk}: {error}')
        try:
            db.session.rollback()
        except Exception:
            pass


def _make_progress(run_pk, log):
    """Progress writer. Every tick doubles as the run's heartbeat."""
    from app import db, TrainingRun

    state = {'at': 0.0, 'phase': None}

    def progress(phase, pct, message=None, **fields):
        now = time.monotonic()
        # Throttle within a phase, but never skip a phase transition - the UI
        # reads the phase, and a dropped transition looks like a stall.
        if phase == state['phase'] and (now - state['at']) < 1.0:
            return
        state['at'], state['phase'] = now, phase
        try:
            db.session.query(TrainingRun).filter_by(id=run_pk).update({
                TrainingRun.phase: phase,
                TrainingRun.progress: max(0, min(100, int(pct))),
                TrainingRun.message: (message or '')[:255],
                TrainingRun.heartbeat_at: _utcnow(),
            }, synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()  # a progress write must never fail the run
            return
        log.debug('training.progress', phase=phase, progress=int(pct), **fields)

    return progress


def _execute(app, run_pk, run_id):
    from app import (db, Chatbot, Document, TrainingRun, record_token_usage,
                     resolve_model_for_chatbot, load_document_bytes)
    from services.chatbot_trainer import get_trainer
    from services.document_processor import DocumentProcessor

    run = db.session.get(TrainingRun, run_pk)
    if run is None or run.status == 'cancelled':
        return

    chatbot = db.session.get(Chatbot, run.chatbot_id)
    if chatbot is None:
        _fail_run(run_pk, 'internal', 'chatbot no longer exists')
        return

    log = RunLogger(_log, run_id=run_id, chatbot_id=chatbot.id, user_id=run.user_id)

    model_alias = resolve_model_for_chatbot(chatbot)
    documents = Document.query.filter_by(chatbot_id=chatbot.id).all()

    run.status = 'running'
    run.phase = 'extracting'
    run.progress = 5
    run.message = 'Reading documents...'
    run.started_at = _utcnow()
    run.heartbeat_at = _utcnow()
    run.host = host_id()
    run.model_alias = model_alias
    run.doc_count = len(documents)
    db.session.commit()

    log = log.bind(model_alias=model_alias)
    log.event('training.started', thread=threading.current_thread().name,
              host=run.host, doc_count=len(documents))

    started = time.monotonic()
    deadline = started + RUN_DEADLINE_SECONDS
    progress = _make_progress(run_pk, log)
    counter = {'attempts': 0}
    usage_sink, embedding_usage_sink = [], []

    try:
        if not documents:
            raise TrainingError('no_documents', 'no documents uploaded', phase='extracting')

        processor = DocumentProcessor()
        documents_text = []
        for position, document in enumerate(documents, start=1):
            extract_started = time.monotonic()
            data = load_document_bytes(document)
            if data is None:
                raise TrainingError('file_missing',
                                    f'document file not found: {document.original_filename}',
                                    phase='extracting', files=document.original_filename)
            # Extract straight from bytes - every extractor accepts a stream, so
            # a document in object storage needs no temp file on the way in.
            text = processor.process_bytes(document.original_filename, data) or ''
            documents_text.append((document.original_filename, text))
            log.event('training.extract.doc', filename=document.original_filename,
                      bytes=len(data), chars=len(text),
                      ms=int((time.monotonic() - extract_started) * 1000))
            progress('extracting', 5 + int(20.0 * position / max(1, len(documents))),
                     f'Reading documents ({position} of {len(documents)})...')

        total_chars = sum(len(text) for _source, text in documents_text)
        log.event('training.extract.done', doc_count=len(documents_text), chars=total_chars,
                  empty_files=[s for s, t in documents_text if not t.strip()])
        run.char_count = total_chars
        db.session.commit()

        summary = get_trainer().train_chatbot(
            chatbot.id, documents_text,
            chatbot_info={'name': chatbot.name, 'description': chatbot.description or ''},
            model_alias=model_alias, usage_sink=usage_sink,
            embedding_usage_sink=embedding_usage_sink, progress=progress,
            run_id=run_id, deadline=deadline, logger=log, counter=counter)

        # Only now, with a complete artifact on disk, does anything claim success.
        run = db.session.get(TrainingRun, run_pk)
        if run is None or run.status == 'cancelled':
            return
        chatbot = db.session.get(Chatbot, run.chatbot_id)
        chatbot.is_trained = True
        chatbot.last_trained_at = _utcnow()
        chatbot.last_training_run_id = run_id
        for document in Document.query.filter_by(chatbot_id=chatbot.id).all():
            # 'processed' now means "included in the last successful training",
            # not merely "we read the file". A failed run leaves it False.
            document.processed = True

        run.status = 'succeeded'
        run.phase = 'done'
        run.progress = 100
        run.message = (f"Indexed {summary['chunk_count']} sections and "
                       f"{summary['fact_count']} facts.")
        run.chunk_count = summary['chunk_count']
        run.char_count = summary['char_count']
        run.finished_at = _utcnow()
        run.heartbeat_at = _utcnow()
        db.session.commit()

        log.event('training.succeeded', duration_ms=int((time.monotonic() - started) * 1000),
                  chunk_count=summary['chunk_count'], fact_count=summary['fact_count'],
                  qa_count=summary['qa_count'], degraded=summary['degraded'],
                  api_attempts=counter['attempts'])

    except TrainingError as error:
        _fail_run(run_pk, error.code, str(error), phase=error.phase)
    except Exception as error:
        _fail_run(run_pk, getattr(error, 'code', 'internal'), str(error))
    finally:
        # Usage is recorded on both paths: a failed run still spent the money,
        # so the meter has to match the invoice.
        _record_usage(run_pk, usage_sink, embedding_usage_sink, counter)


def _record_usage(run_pk, usage_sink, embedding_usage_sink, counter):
    from app import db, TrainingRun, record_token_usage

    def total(sink, key):
        return sum(int(item.get(key) or 0) for item in sink)

    try:
        db.session.rollback()
        run = db.session.get(TrainingRun, run_pk)
        if run is None:
            return

        run.prompt_tokens = total(usage_sink, 'prompt_tokens')
        run.completion_tokens = total(usage_sink, 'completion_tokens')
        run.total_tokens = total(usage_sink, 'total_tokens')
        run.embedding_tokens = total(embedding_usage_sink, 'total_tokens')
        run.api_attempts = counter.get('attempts', 0)
        db.session.commit()

        for usage in usage_sink:
            record_token_usage(run.user_id, run.chatbot_id, usage, source='training')
        for usage in embedding_usage_sink:
            record_token_usage(run.user_id, run.chatbot_id, usage, source='embedding')
    except Exception as error:
        _log.error(f'could not record token usage for run {run_pk}: {error}')
        try:
            db.session.rollback()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Stale-run reaper
# ----------------------------------------------------------------------

def reap_stale_runs(boot=False, force=False):
    """Mark runs whose worker is gone as 'orphaned'. Returns how many.

    A daemon thread dies with the process, so without this a Render restart
    would leave rows stuck at 'running' forever and a browser polling them
    would never stop.
    """
    global _last_reap

    if not (boot or force):
        with _reap_lock:
            if (time.monotonic() - _last_reap) < REAP_THROTTLE_SECONDS:
                return 0
            _last_reap = time.monotonic()

    from app import db, TrainingRun

    try:
        cutoff = _utcnow() - timedelta(seconds=STALE_AFTER_SECONDS)
        query = TrainingRun.query.filter(TrainingRun.status.in_(('queued', 'running')))
        if boot:
            # A fresh process has no live worker threads, so anything this
            # host:pid owned is definitionally dead. Rows owned by another host
            # are reaped on heartbeat age only - which keeps this correct if
            # --workers is ever raised above 1.
            query = query.filter(db.or_(TrainingRun.host == host_id(),
                                        TrainingRun.heartbeat_at < cutoff))
        else:
            query = query.filter(db.or_(
                TrainingRun.heartbeat_at < cutoff,
                # A run enqueued seconds ago has no heartbeat yet; the
                # created_at guard keeps the reaper from killing it.
                db.and_(TrainingRun.heartbeat_at.is_(None),
                        TrainingRun.created_at < cutoff)))

        stale = query.all()
        for run in stale:
            age = None
            if run.heartbeat_at:
                age = int((_utcnow() - run.heartbeat_at).total_seconds())
            run.status = 'orphaned'
            run.error_code = 'interrupted'
            run.error_message = 'the server restarted while this run was in progress'
            run.finished_at = _utcnow()
            RunLogger(_log, run_id=run.run_id, chatbot_id=run.chatbot_id).warning(
                'training.reaped', age_seconds=age, phase=run.phase, host=run.host)
        if stale:
            db.session.commit()
        return len(stale)
    except Exception as error:
        _log.error(f'stale-run reaper failed: {error}')
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0
