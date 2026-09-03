#!/usr/bin/env python3
"""Phase 3 end-to-end rehearsal against the LIVE Postgres and the LIVE Bunny zones.

    python qa_phase3_live_prod.py --confirm-prod
    python qa_phase3_live_prod.py --cleanup <manifest.json>

Everything happens under one dedicated throwaway user, and every row and object
it creates is appended to a manifest file the moment it is created - so a crash
half way through is recoverable with --cleanup instead of a hunt through the
production database.

This is deliberately not the same script as qa_phase4_live_app.py. That one
proves the storage layer against a scratch SQLite database; this one proves the
Phase 3 training path against the database the customers are actually in, which
is the only place a schema drift or a plan-gating mistake shows up.

Costs real money: two training runs plus a dozen chat turns on gpt-5-mini and
gpt-4.1, and one deliberately failing run that spends nothing.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from dotenv import load_dotenv

load_dotenv(os.path.join(HERE, '.env'))
os.environ.setdefault('LOG_LEVEL', 'WARNING')

SAMPLE_DOCS = os.path.join(HERE, 'sample_docs')
SAMPLE_FILES = [
    'northwind_faq.txt',
    'northwind_handbook.pdf',
    'northwind_products.docx',
    'northwind_catalog.json',
    'northwind_pricing.xlsx',
]

# question -> substrings the answer must contain. One per file type, plus the
# out-of-scope question that a bot which invents answers will fail.
CHAT_MATRIX = [
    ('txt',  'What is order code NW-4471 and how quickly does it ship?',
     [['NW-4471'], ['2 business days', 'two business days']]),
    ('pdf',  'What is return policy PX-820 and how many days do I have to return a bag?',
     [['PX-820'], ['45']]),
    ('docx', 'How much does the Aurora burr grinder cost?',
     [['284.50']]),
    ('json', 'What is the SKU for the Kilimanjaro Light coffee?',
     [['KL-9006']]),
    ('xlsx', 'What is the wholesale tier 3 price per pound?',
     [['18.75']]),
]

DECLINE_MARKERS = [
    'do not', "don't", 'does not', "doesn't", 'not have', 'no information',
    'unable', 'only sell', 'only offer', 'we sell coffee', 'not something',
    'afraid', 'cannot', "can't", 'no laptops', 'not carry',
]

RESULTS = []


def check(name, passed, detail=''):
    RESULTS.append((name, bool(passed), detail))
    print(('  PASS  ' if passed else '  FAIL  ') + name + (' [%s]' % detail if detail else ''))
    return bool(passed)


def banner(title):
    print()
    print('=' * 72)
    print(title)
    print('=' * 72)


# ----------------------------------------------------------------------
# Manifest: written after every creation so cleanup never relies on memory
# ----------------------------------------------------------------------

class Manifest(object):
    def __init__(self, path):
        self.path = path
        self.data = {'created_at': datetime.utcnow().isoformat() + 'Z',
                     'user_id': None, 'username': None, 'chatbot_ids': [],
                     'objects': []}
        self.flush()

    def flush(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(self.data, handle, indent=2)

    def set_user(self, user_id, username):
        self.data['user_id'] = user_id
        self.data['username'] = username
        self.flush()

    def add_chatbot(self, chatbot_id):
        self.data['chatbot_ids'].append(chatbot_id)
        self.flush()

    def add_object(self, zone, key):
        entry = [zone, key]
        if entry not in self.data['objects']:
            self.data['objects'].append(entry)
            self.flush()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def db_summary():
    """Host and database name only - never the credentials."""
    import re
    url = (os.environ.get('DATABASE_URL') or '').strip().strip('"').strip("'")
    return re.sub(r'://[^@]*@', '://***@', url)


def poll_to_terminal(client, chatbot_id, run_id, timeout=1800):
    """Poll the status endpoint the way the browser does. Returns the run plus
    the phase and progress sequences, so a regression in ordering is visible."""
    phases, progresses, final = [], [], None
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get('/train_chatbot/%d/status?run_id=%s' % (chatbot_id, run_id)).get_json()
        run = (payload or {}).get('run') or {}
        if run.get('phase') and (not phases or phases[-1] != run['phase']):
            phases.append(run['phase'])
        if run.get('progress') is not None:
            progresses.append(run['progress'])
        if run.get('terminal'):
            final = run
            break
        time.sleep(2)
    return final, phases, progresses


def upload_sample_docs(client, chatbot_id, storage, manifest, app, Document, alias):
    """Upload all five fixtures through the real route and verify each object."""
    import services.object_storage as st

    for name in SAMPLE_FILES:
        with open(os.path.join(SAMPLE_DOCS, name), 'rb') as handle:
            raw = handle.read()
        response = client.post(
            '/upload_document/%d' % chatbot_id,
            data={'file': (io.BytesIO(raw), name)},
            content_type='multipart/form-data',
            headers={'X-Requested-With': 'XMLHttpRequest'})
        body = response.get_json() or {}
        if not check('%s: %s uploaded' % (alias, name),
                     response.status_code == 200 and body.get('success'),
                     str(body)[:90]):
            continue

        with app.app_context():
            document = (Document.query
                        .filter_by(chatbot_id=chatbot_id, original_filename=name)
                        .first())
            key = document.storage_key if document else None
            legacy_path = document.file_path if document else None

        expected_prefix = 'documents/%d/' % chatbot_id
        check('%s: %s has a sharded storage key' % (alias, name),
              bool(key) and key.startswith(expected_prefix) and key.endswith(name),
              key or 'none')
        check('%s: %s leaves the legacy file_path empty' % (alias, name),
              not legacy_path, repr(legacy_path))
        if key:
            manifest.add_object(st.PRIVATE, key)
            stored = storage.get(st.PRIVATE, key)
            check('%s: %s is byte-identical in the private zone' % (alias, name),
                  stored == raw, '%d vs %d bytes' % (len(stored), len(raw)))


def wait_for_usage(app, TokenUsage, user_id, chatbot_id, timeout=60):
    """Token usage is recorded in the runner's finally block, which runs after
    the run is committed as terminal - so a poller that stops at 'succeeded' can
    read the meter mid-write. Wait for it rather than racing it."""
    deadline = time.time() + timeout
    by_source = {}
    while time.time() < deadline:
        with app.app_context():
            rows = TokenUsage.query.filter_by(user_id=user_id, chatbot_id=chatbot_id).all()
        by_source = {}
        for row in rows:
            by_source[row.source] = by_source.get(row.source, 0) + (row.total_tokens or 0)
        if by_source.get('training', 0) > 0 and by_source.get('embedding', 0) > 0:
            return by_source
        time.sleep(2)
    return by_source


def artifact_bytes(storage, chatbot_id):
    import services.object_storage as st
    try:
        return storage.get(st.PRIVATE, st.artifact_key(chatbot_id))
    except Exception:
        return None


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------

def run(manifest_path):
    import services.object_storage as st
    from werkzeug.security import generate_password_hash
    from app import (create_app, db, User, Chatbot, Document, Plan, UserSubscription,
                     TokenUsage, Conversation, get_allowed_models,
                     resolve_model_for_chatbot)

    banner('Pre-flight')
    print('database:', db_summary())
    storage = st.get_storage()
    print('storage :', storage.name)
    if not check('storage backend is Bunny', storage.name == 'bunny', storage.name):
        return
    if not check('database is the live Postgres', 'postgresql' in db_summary()):
        return
    missing = [name for name in SAMPLE_FILES
               if not os.path.exists(os.path.join(SAMPLE_DOCS, name))]
    if not check('sample corpus present', not missing,
                 'missing: %s' % missing if missing else '%d files' % len(SAMPLE_FILES)):
        return

    app = create_app()
    manifest = Manifest(manifest_path)
    print('manifest:', manifest_path)

    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    username = 'qa_phase3_%s' % stamp

    # ------------------------------------------------------------------ setup
    banner('Test account on an existing plan')
    with app.app_context():
        # An existing plan, not a new one: the point is to prove gating against
        # the ladder the customers are actually on.
        plan = Plan.query.filter_by(name='Basic').first()
        if plan is None:
            check('Basic plan exists', False, 'no plan named Basic')
            return
        allowed = get_allowed_models(plan)
        check('plan allows both tiers under test', 'luna' in allowed and 'terra' in allowed,
              str(allowed))

        user = User(username=username, email='%s@qa.invalid' % username,
                    password_hash=generate_password_hash(uuid.uuid4().hex))
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        db.session.add(UserSubscription(user_id=user_id, plan_id=plan.id,
                                        status='active', created_at=datetime.utcnow()))
        db.session.commit()
    manifest.set_user(user_id, username)
    print('test user: %s (id=%d)' % (username, user_id))

    bots = {}
    with app.app_context():
        for alias in ('luna', 'terra'):
            bot = Chatbot(name='QA Phase3 %s %s' % (alias, stamp),
                          # url_name matters: the dashboard builds a link from
                          # it, so a chatbot without one 500s the page the
                          # delete route redirects to.
                          url_name='qa-phase3-%s-%s' % (alias, stamp),
                          description='Phase 3 QA fixture - safe to delete',
                          embed_code=str(uuid.uuid4()), user_id=user_id,
                          model_alias=alias)
            db.session.add(bot)
            db.session.commit()
            bots[alias] = {'id': bot.id, 'embed_code': bot.embed_code}
            manifest.add_chatbot(bot.id)
        for alias, info in bots.items():
            bot = Chatbot.query.get(info['id'])
            resolved = resolve_model_for_chatbot(bot)
            check('%s bot resolves to %s (no silent plan downgrade)' % (alias, alias),
                  resolved == alias, resolved)

    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True

    # ------------------------------------------------------- upload + train
    for alias in ('luna', 'terra'):
        chatbot_id = bots[alias]['id']
        banner('%s: upload the sample corpus to Bunny' % alias.upper())
        upload_sample_docs(client, chatbot_id, storage, manifest, app, Document, alias)

        banner('%s: training run' % alias.upper())
        started = time.time()
        response = client.post('/train_chatbot/%d' % chatbot_id,
                               headers={'X-Requested-With': 'XMLHttpRequest'})
        body = response.get_json() or {}
        run_id = body.get('run_id')
        if not check('%s: training accepted with 202' % alias,
                     response.status_code == 202 and bool(run_id),
                     '%s %s' % (response.status_code, str(body)[:60])):
            continue

        second = client.post('/train_chatbot/%d' % chatbot_id,
                             headers={'X-Requested-With': 'XMLHttpRequest'})
        second_body = second.get_json() or {}
        check('%s: a second click attaches to the running run (409)' % alias,
              second.status_code == 409 and second_body.get('run_id') == run_id,
              '%s %s' % (second.status_code, second_body.get('run_id')))

        final, phases, progresses = poll_to_terminal(client, chatbot_id, run_id)
        elapsed = time.time() - started
        bots[alias]['run'] = final
        bots[alias]['seconds'] = elapsed
        if not check('%s: run reached succeeded' % alias,
                     final and final.get('status') == 'succeeded',
                     '%s/%s %s' % ((final or {}).get('status'),
                                   (final or {}).get('error_code'),
                                   (final or {}).get('error_message') or '')):
            continue
        print('    %s: %.1fs, phases: %s' % (alias, elapsed, ' -> '.join(phases)))
        check('%s: progress never goes backwards' % alias,
              all(b >= a for a, b in zip(progresses, progresses[1:])),
              '%d..%d' % (min(progresses), max(progresses)) if progresses else 'none')
        check('%s: phases run in order' % alias,
              phases[0] in ('queued', 'extracting') and phases[-1] == 'done',
              ' -> '.join(phases))
        check('%s: run recorded the tier it actually used' % alias,
              final.get('model_alias') == alias, str(final.get('model_alias')))

        # ------------------------------------------------------- artifact
        raw = artifact_bytes(storage, chatbot_id)
        manifest.add_object(st.PRIVATE, st.artifact_key(chatbot_id))
        if not check('%s: knowledge base is in the private zone' % alias, bool(raw),
                     '%d bytes' % len(raw) if raw else 'absent'):
            continue
        artifact = json.loads(raw.decode('utf-8'))
        index = artifact.get('index') or {}
        sources = artifact.get('sources') or []
        check('%s: artifact is schema v3' % alias, artifact.get('schema_version') == 3,
              str(artifact.get('schema_version')))
        check('%s: artifact records the tier' % alias,
              artifact.get('model_alias') == alias, str(artifact.get('model_alias')))
        check('%s: all five documents are listed as sources' % alias,
              len(sources) == 5 and all((s.get('chars') or 0) > 0 for s in sources),
              ', '.join('%s:%s' % (s.get('filename'), s.get('chars')) for s in sources))
        check('%s: embeddings came from the OpenAI model' % alias,
              index.get('embedding_model') == 'text-embedding-3-small',
              str(index.get('embedding_model')))
        check('%s: vectors are 512-dimensional and normalized' % alias,
              index.get('dimensions') == 512 and index.get('normalized') is True,
              '%s dims, normalized=%s' % (index.get('dimensions'), index.get('normalized')))
        check('%s: index has one vector per chunk' % alias,
              index.get('count') == len(index.get('chunks') or [])
              and index.get('count') == len(index.get('vectors_b64') or []),
              'count=%s chunks=%d vectors=%d' % (index.get('count'),
                                                 len(index.get('chunks') or []),
                                                 len(index.get('vectors_b64') or [])))
        check('%s: knowledge base has facts' % alias,
              len(artifact.get('kb_facts') or []) > 0,
              '%d facts, %d qa patterns' % (len(artifact.get('kb_facts') or []),
                                            len(artifact.get('qa_patterns') or [])))
        check('%s: run was not degraded' % alias, artifact.get('degraded') is False,
              str(artifact.get('degraded')))

        # ------------------------------------------------------- db state
        with app.app_context():
            bot = Chatbot.query.get(chatbot_id)
            documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
        check('%s: chatbot marked trained with a run id' % alias,
              bot.is_trained and bot.last_trained_at and bot.last_training_run_id == run_id,
              str(bot.last_training_run_id))
        check('%s: every document marked processed' % alias,
              len(documents) == 5 and all(d.processed for d in documents),
              '%d/%d' % (sum(1 for d in documents if d.processed), len(documents)))
        by_source = wait_for_usage(app, TokenUsage, user_id, chatbot_id)
        check('%s: training and embedding metered separately' % alias,
              by_source.get('training', 0) > 0 and by_source.get('embedding', 0) > 0,
              str(by_source))
        bots[alias]['tokens'] = by_source

    # ------------------------------------------------------------ chat
    for alias in ('luna', 'terra'):
        info = bots[alias]
        if not info.get('run') or info['run'].get('status') != 'succeeded':
            continue
        banner('%s: does the bot answer from what it learned?' % alias.upper())
        answers = {}
        for label, question, expectations in CHAT_MATRIX:
            response = client.post('/api/chat/%s' % info['embed_code'],
                                   json={'message': question})
            answer = ((response.get_json() or {}).get('response') or '')
            answers[label] = answer
            lowered = answer.lower()
            missed = [group for group in expectations
                      if not any(option.lower() in lowered for option in group)]
            check('%s: %s fact recalled' % (alias, label), not missed,
                  answer.replace(chr(10), ' ')[:100])

        response = client.post('/api/chat/%s' % info['embed_code'],
                               json={'message': 'Do you sell laptops?'})
        answer = ((response.get_json() or {}).get('response') or '')
        lowered = answer.lower()
        check('%s: declines an out-of-scope question' % alias,
              any(marker in lowered for marker in DECLINE_MARKERS),
              answer.replace(chr(10), ' ')[:100])
        info['answers'] = answers

        with app.app_context():
            conversations = Conversation.query.filter_by(chatbot_id=info['id']).all()
        check('%s: conversations record the tier and token counts' % alias,
              conversations
              and all(c.model_alias == alias for c in conversations)
              and all((c.total_tokens or 0) > 0 for c in conversations),
              '%d rows, aliases=%s' % (len(conversations),
                                       sorted({c.model_alias for c in conversations})))

    # ------------------------------------------- OWL-9: no silent success
    banner('OWL-9: a failed retrain must not destroy working training')
    luna_id = bots['luna']['id']
    before = artifact_bytes(storage, luna_id)
    if before and bots['luna'].get('run', {}).get('status') == 'succeeded':
        before_digest = hashlib.sha256(before).hexdigest()
        with app.app_context():
            usage_before = sum((r.total_tokens or 0) for r in
                               TokenUsage.query.filter_by(user_id=user_id).all())

        from openai import OpenAI
        from services.chatbot_trainer import get_trainer
        trainer = get_trainer()
        embeddings = trainer.embeddings
        real_trainer, real_embed = trainer.openai_client, embeddings.client
        trainer.openai_client = OpenAI(api_key='sk-invalid-key-for-qa', max_retries=0, timeout=30.0)
        embeddings.client = OpenAI(api_key='sk-invalid-key-for-qa', max_retries=0, timeout=30.0)
        embeddings._query_cache.clear()
        try:
            started = time.time()
            response = client.post('/train_chatbot/%d' % luna_id,
                                   headers={'X-Requested-With': 'XMLHttpRequest'})
            bad_run_id = (response.get_json() or {}).get('run_id')
            final, _phases, _progress = poll_to_terminal(client, luna_id, bad_run_id, timeout=300)
            elapsed = time.time() - started
        finally:
            trainer.openai_client, embeddings.client = real_trainer, real_embed
            embeddings._query_cache.clear()

        check('a bad key fails loudly with openai_auth',
              final and final.get('status') == 'failed'
              and final.get('error_code') == 'openai_auth',
              '%s/%s' % ((final or {}).get('status'), (final or {}).get('error_code')))
        check('the failure is fast (auth is never retried)', elapsed < 90, '%.1fs' % elapsed)
        check('the failure has user-facing copy, not a stack trace',
              bool((final or {}).get('friendly_error'))
              and 'Traceback' not in ((final or {}).get('friendly_error') or ''),
              ((final or {}).get('friendly_error') or '')[:90])

        after = artifact_bytes(storage, luna_id)
        check('the previous knowledge base is byte-identical',
              after is not None and hashlib.sha256(after).hexdigest() == before_digest)
        with app.app_context():
            bot = Chatbot.query.get(luna_id)
            usage_after = sum((r.total_tokens or 0) for r in
                              TokenUsage.query.filter_by(user_id=user_id).all())
        check('the chatbot is still marked trained', bot.is_trained)
        check('the bot still answers after the failed retrain',
              '284.50' in ((client.post('/api/chat/%s' % bots['luna']['embed_code'],
                                        json={'message': 'How much is the Aurora burr grinder?'})
                            .get_json() or {}).get('response') or ''))
        check('a fatal auth failure spends no tokens',
              usage_after == usage_before, '%d -> %d' % (usage_before, usage_after))

    # ------------------------------------- guard: whitespace-only document
    banner('OWL-9: an unreadable document fails before any spend')
    with app.app_context():
        blank_bot = Chatbot(name='QA Phase3 blank %s' % stamp,
                            url_name='qa-phase3-blank-%s' % stamp,
                            description='Phase 3 QA fixture - safe to delete',
                            embed_code=str(uuid.uuid4()), user_id=user_id,
                            model_alias='luna')
        db.session.add(blank_bot)
        db.session.commit()
        blank_id = blank_bot.id
    manifest.add_chatbot(blank_id)

    client.post('/upload_document/%d' % blank_id,
                data={'file': (io.BytesIO(b'   \r\n\t   \r\n   '), 'blank_scan.txt')},
                content_type='multipart/form-data',
                headers={'X-Requested-With': 'XMLHttpRequest'})
    with app.app_context():
        blank_doc = Document.query.filter_by(chatbot_id=blank_id).first()
        if blank_doc and blank_doc.storage_key:
            manifest.add_object(st.PRIVATE, blank_doc.storage_key)
        usage_before = sum((r.total_tokens or 0) for r in
                           TokenUsage.query.filter_by(user_id=user_id).all())

    response = client.post('/train_chatbot/%d' % blank_id,
                           headers={'X-Requested-With': 'XMLHttpRequest'})
    blank_run_id = (response.get_json() or {}).get('run_id')
    final, _phases, _progress = poll_to_terminal(client, blank_id, blank_run_id, timeout=180)
    check('a whitespace-only document fails with no_text_extracted',
          final and final.get('status') == 'failed'
          and final.get('error_code') == 'no_text_extracted',
          '%s/%s' % ((final or {}).get('status'), (final or {}).get('error_code')))
    check('no knowledge base was written for the failed run',
          artifact_bytes(storage, blank_id) is None)
    with app.app_context():
        blank_bot = Chatbot.query.get(blank_id)
        usage_after = sum((r.total_tokens or 0) for r in
                          TokenUsage.query.filter_by(user_id=user_id).all())
    check('the chatbot was not marked trained', not blank_bot.is_trained)
    check('the guard spends nothing', usage_after == usage_before,
          '%d -> %d' % (usage_before, usage_after))

    return {'app': app, 'client': client, 'manifest': manifest, 'user_id': user_id,
            'bots': bots, 'blank_id': blank_id, 'storage': storage}


# ----------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------

def cleanup(manifest_path, client=None, app=None):
    """Remove everything the run created. Safe to call twice."""
    import services.object_storage as st

    banner('Cleanup')
    with open(manifest_path, encoding='utf-8') as handle:
        data = json.load(handle)

    if app is None:
        from app import create_app
        app = create_app()
    from app import db, User, Chatbot, Document, Conversation, TokenUsage, TrainingRun, UserSubscription

    if client is None:
        client = app.test_client()
        if data.get('user_id'):
            with client.session_transaction() as session:
                session['_user_id'] = str(data['user_id'])
                session['_fresh'] = True

    # Delete through the app first, because exercising the real delete path is
    # part of the test - but never let it strand rows in production if it
    # raises. The direct sweep below is the backstop.
    for chatbot_id in data.get('chatbot_ids') or []:
        try:
            response = client.post('/delete_chatbot/%d' % chatbot_id, follow_redirects=True)
            check('chatbot %d deleted through the app' % chatbot_id,
                  response.status_code == 200, str(response.status_code))
        except Exception as error:
            check('chatbot %d deleted through the app' % chatbot_id, False,
                  '%s: %s' % (type(error).__name__, str(error)[:80]))

    with app.app_context():
        for chatbot_id in data.get('chatbot_ids') or []:
            try:
                TokenUsage.query.filter_by(chatbot_id=chatbot_id).update(
                    {TokenUsage.chatbot_id: None}, synchronize_session=False)
                TrainingRun.query.filter_by(chatbot_id=chatbot_id).delete(synchronize_session=False)
                Conversation.query.filter_by(chatbot_id=chatbot_id).delete(synchronize_session=False)
                Document.query.filter_by(chatbot_id=chatbot_id).delete(synchronize_session=False)
                Chatbot.query.filter_by(id=chatbot_id).delete(synchronize_session=False)
                db.session.commit()
            except Exception as error:
                db.session.rollback()
                print('  (direct sweep failed for chatbot %d: %s)' % (chatbot_id, error))

    storage = st.get_storage()
    stragglers = 0
    for zone, key in data.get('objects') or []:
        try:
            if storage.exists(zone, key):
                storage.delete(zone, key)
                stragglers += 1
        except Exception as error:
            print('  (could not remove %s:%s - %s)' % (zone, key, error))
    print('  removed %d object(s) the app had not already deleted' % stragglers)

    user_id = data.get('user_id')
    if user_id:
        with app.app_context():
            for model in (TrainingRun, TokenUsage):
                model.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            UserSubscription.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

            residue = {
                'chatbot': Chatbot.query.filter_by(user_id=user_id).count(),
                'training_run': TrainingRun.query.filter_by(user_id=user_id).count(),
                'token_usage': TokenUsage.query.filter_by(user_id=user_id).count(),
                'subscription': UserSubscription.query.filter_by(user_id=user_id).count(),
                'user': User.query.filter_by(id=user_id).count(),
            }
            for chatbot_id in data.get('chatbot_ids') or []:
                residue['document'] = residue.get('document', 0) + \
                    Document.query.filter_by(chatbot_id=chatbot_id).count()
                residue['conversation'] = residue.get('conversation', 0) + \
                    Conversation.query.filter_by(chatbot_id=chatbot_id).count()
        check('no test rows remain in the live database',
              not any(residue.values()), str(residue))

    leftover = []
    for zone, key in data.get('objects') or []:
        try:
            if storage.exists(zone, key):
                leftover.append(key)
        except Exception:
            pass
    check('no test objects remain in Bunny', not leftover, str(leftover))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-prod', action='store_true',
                        help='required: this writes to the live database and the live zones')
    parser.add_argument('--cleanup', metavar='MANIFEST',
                        help='remove everything listed in a manifest from an earlier run')
    parser.add_argument('--manifest', default=os.path.join(
        HERE, 'qa_phase3_manifest_%s.json' % datetime.utcnow().strftime('%Y%m%d%H%M%S')))
    args = parser.parse_args()

    if args.cleanup:
        cleanup(args.cleanup)
    else:
        if not args.confirm_prod:
            print('Refusing to run without --confirm-prod: this test writes to the live '
                  'database and the live Bunny zones.')
            return 2
        context = None
        try:
            context = run(args.manifest)
        finally:
            if context:
                cleanup(args.manifest, context['client'], context['app'])
            else:
                print('\nrun aborted before setup; nothing to clean up')

    banner('SUMMARY')
    failed = [name for name, passed, _ in RESULTS if not passed]
    print('%d/%d checks passed' % (len(RESULTS) - len(failed), len(RESULTS)))
    for name in failed:
        print('  FAILED:', name)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
