#!/usr/bin/env python3
"""Phase 3 QA harness: training reliability (OWL-8 .. OWL-13).

Runs against a scratch SQLite database and a scratch training_data directory, so
it never touches the real local DB and never touches Render.

    python qa_phase3.py                # fault injection only, no API spend
    python qa_phase3.py --live         # + real OpenAI runs on every model tier

The fault-injection suite monkeypatches the OpenAI clients, so it costs nothing
and can run in CI. --live is what proves the tiers behave, and needs a real
OPENAI_API_KEY in .env.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix='owlbee_phase3_qa_')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(SCRATCH, 'qa.db').replace(os.sep, '/')
os.environ['LOCAL_STORAGE_PRIVATE_DIR'] = os.path.join(SCRATCH, 'private')
os.environ['LOCAL_STORAGE_PUBLIC_DIR'] = os.path.join(SCRATCH, 'public')
# Force the local backend. Empty rather than deleted, deliberately: app.py calls
# load_dotenv(), which will not override a key already in the environment but
# would repopulate a deleted one from .env - which would silently write this
# suite's fixtures into the real Bunny zones.
for _k in ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ZONE', 'BUNNY_PUBLIC_ACCESS_KEY',
           'BUNNY_PUBLIC_CDN_URL', 'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY',
           'BUNNY_STORAGE_HOST_PRIVATE'):
    os.environ[_k] = ''
os.environ.setdefault('LOG_LEVEL', 'WARNING')

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
# Fixtures
# ----------------------------------------------------------------------

SMALL_FAQ = """Acme Robotics FAQ

What are your business hours?
We are open Monday to Friday, 9am to 5pm Pacific Time.

Where are you located?
Our office is at 44 Harbour Road, Portland, Oregon.

How much does the Starter plan cost?
The Starter plan is $49 per month and includes three robots.

Do you offer support?
Yes, email support@acmerobotics.example and we reply within one business day.

What is your return policy?
Hardware may be returned within 30 days for a full refund.
"""

# A long document whose key fact sits in the middle - the case that the old
# "inline the whole corpus into one prompt" design could not answer.
BURIED_FACT = 'The internal warranty escalation code for damaged servos is ZULU-774.'


def build_handbook():
    filler = ("Acme Robotics builds industrial arms for small manufacturers. "
              "Our engineering team documents every procedure in this handbook. "
              "Safety checks are performed before every shift. ")
    parts = [filler * 40 for _ in range(14)]
    parts.insert(7, "Warranty escalation. " + BURIED_FACT + " "
                    "Only support leads may use this code. ")
    return '\n\n'.join(parts)


def write_fixtures(directory):
    os.makedirs(directory, exist_ok=True)
    files = {
        'small_faq.txt': SMALL_FAQ,
        'handbook.txt': build_handbook(),
        'scanned.pdf.txt': '   \n  \n ',          # extracts nothing
        'empty.txt': '',
        'huge.txt': 'x' * 1_600_000,
        'weird.txt': ('Prices in EUR €. Emoji: \U0001f916 ✅. '
                      'Arabic: مرحبا. '
                      'A literal fence follows: ```json {"not": "real"} ``` '
                      'The support email is weird@acmerobotics.example. ' * 6),
    }
    for name, content in files.items():
        with open(os.path.join(directory, name), 'w', encoding='utf-8') as handle:
            handle.write(content)
    return files


# ----------------------------------------------------------------------
# App / DB scaffolding
# ----------------------------------------------------------------------

def make_app():
    from app import create_app
    from services.object_storage import get_storage
    app = create_app()
    assert get_storage().name == 'local', (
        'this suite must run on local storage; got ' + get_storage().name)
    return app


def seed(app, fixtures_dir, filenames, model_alias, username):
    """Create a user, plan, chatbot and its documents. Returns the chatbot id."""
    from app import db, User, Chatbot, Document, Plan, UserSubscription
    from werkzeug.security import generate_password_hash
    from datetime import datetime
    import uuid

    with app.app_context():
        plan = Plan.query.filter_by(name='QA').first()
        if plan is None:
            plan = Plan(name='QA', description='QA plan', monthly_price=0, yearly_price=0,
                        chatbot_limit=99, file_size_limit_mb=50,
                        allowed_models=json.dumps(['luna', 'terra', 'sol']),
                        monthly_token_limit=None, web_search_enabled=False, is_active=True)
            db.session.add(plan)
            db.session.commit()

        # Real deployments have this seeded by migrate_add_training_prompt.py;
        # seed it here too so QA exercises the same prompt path as production.
        from app import Settings
        if not Settings.query.filter_by(key='training_prompt').first():
            db.session.add(Settings(key='training_prompt', value=(
                '{base_prompt}\n\n'
                'Use the following information from the training documents to answer '
                'the user. If the answer is not present, say you do not have that '
                'information. Do not mention file names or relevance scores.\n\n'
                '{context}')))
            db.session.commit()
        user = User(username=username, email=f'{username}@example.com',
                    password_hash=generate_password_hash('x'))
        db.session.add(user)
        db.session.commit()

        # The plan comes from a subscription, not a column on User - and it has
        # to allow all three tiers or resolve_model_for_chatbot() caps the bot.
        db.session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status='active',
                                        created_at=datetime.utcnow()))
        db.session.commit()

        chatbot = Chatbot(name=f'QA {username}', description='QA bot',
                          embed_code=str(uuid.uuid4()), user_id=user.id,
                          model_alias=model_alias)
        db.session.add(chatbot)
        db.session.commit()

        for name in filenames:
            path = os.path.join(fixtures_dir, name)
            db.session.add(Document(filename=name, original_filename=name,
                                    file_path=path, chatbot_id=chatbot.id))
        db.session.commit()

        # Make sure nothing is already stored at this id, so "was an artifact
        # written" is a statement about THIS run.
        from services.chatbot_trainer import get_trainer
        get_trainer().delete_chatbot_data(chatbot.id)

        return chatbot.id, user.id


def run_training(app, chatbot_id, user_id, timeout=600):
    """Enqueue a run and block until it reaches a terminal status."""
    from app import db, TrainingRun, TRAINING_TERMINAL_STATUSES
    from services import training_runner

    with app.app_context():
        run, created = training_runner.enqueue_training(app, chatbot_id, user_id)
        run_id = run.run_id

    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.app_context():
            run = TrainingRun.query.filter_by(run_id=run_id).first()
            if run and run.status in TRAINING_TERMINAL_STATUSES:
                return {
                    'run_id': run.run_id, 'status': run.status, 'phase': run.phase,
                    'progress': run.progress, 'message': run.message,
                    'error_code': run.error_code, 'error_message': run.error_message,
                    'model_alias': run.model_alias, 'chunk_count': run.chunk_count,
                    'char_count': run.char_count, 'total_tokens': run.total_tokens,
                    'embedding_tokens': run.embedding_tokens,
                    'api_attempts': run.api_attempts, 'created': created,
                }
        time.sleep(0.5)
    raise AssertionError(f'training run {run_id} did not finish within {timeout}s')


def artifact_of(chatbot_id):
    """(parsed artifact, key) straight from storage, bypassing the cache."""
    from services.chatbot_trainer import get_trainer
    from services.object_storage import PRIVATE, StorageNotFound, get_storage
    key = get_trainer().artifact_key(chatbot_id)
    try:
        return json.loads(get_storage().get(PRIVATE, key).decode('utf-8')), key
    except StorageNotFound:
        return None, key


def sha256_of(chatbot_id):
    """Hash of the stored artifact, or None. Used to prove a failed run left it alone."""
    from services.chatbot_trainer import get_trainer
    from services.object_storage import PRIVATE, StorageNotFound, get_storage
    try:
        blob = get_storage().get(PRIVATE, get_trainer().artifact_key(chatbot_id))
    except StorageNotFound:
        return None
    return hashlib.sha256(blob).hexdigest()


# ----------------------------------------------------------------------
# Fault injection (no API spend)
# ----------------------------------------------------------------------

def test_retry_policy():
    banner('OWL-8: retry / backoff policy (no API calls)')
    import openai
    from services.openai_retry import call_with_retry, OpenAICallFailed

    def make(cls, **kwargs):
        """Build an SDK exception without needing its real constructor signature."""
        error = cls.__new__(cls)
        Exception.__init__(error, 'injected')
        for key, value in kwargs.items():
            setattr(error, key, value)
        return error

    # transient failures then success
    state = {'n': 0}
    counter = {'attempts': 0}

    def flaky():
        state['n'] += 1
        if state['n'] <= 2:
            raise make(openai.APIConnectionError, request=None)
        return 'ok'

    result = call_with_retry(flaky, op='qa', attempts=4, base_delay=0.01, counter=counter)
    check('transient errors retried then succeed', result == 'ok' and counter['attempts'] == 3,
          f"attempts={counter['attempts']}")

    # fatal: no retries at all
    counter = {'attempts': 0}

    def unauthorized():
        raise make(openai.AuthenticationError, response=None, body=None)

    try:
        call_with_retry(unauthorized, op='qa', attempts=4, base_delay=0.01, counter=counter)
        check('auth error is fatal', False, 'no exception raised')
    except OpenAICallFailed as error:
        check('auth error is fatal, zero retries',
              error.code == 'openai_auth' and counter['attempts'] == 1,
              f"code={error.code} attempts={counter['attempts']}")

    # exhaustion
    counter = {'attempts': 0}

    def always_rate_limited():
        raise make(openai.RateLimitError, response=None, body=None)

    try:
        call_with_retry(always_rate_limited, op='qa', attempts=3, base_delay=0.01, counter=counter)
        check('rate limit exhausts', False, 'no exception raised')
    except OpenAICallFailed as error:
        check('rate limit retried then exhausts',
              error.code == 'openai_unavailable' and counter['attempts'] == 3,
              f"attempts={counter['attempts']}")

    # a bug on our side is not a network blip - it must propagate untouched
    def our_bug():
        raise ValueError('parsing bug')

    try:
        call_with_retry(our_bug, op='qa', attempts=3, base_delay=0.01)
        check('non-API errors propagate', False, 'swallowed')
    except ValueError:
        check('non-API errors propagate unchanged', True)
    except Exception as error:
        check('non-API errors propagate unchanged', False, type(error).__name__)

    # deadline stops the retry loop rather than sleeping past it
    counter = {'attempts': 0}
    try:
        call_with_retry(always_rate_limited, op='qa', attempts=6, base_delay=5.0,
                        deadline=time.monotonic() + 0.05, counter=counter)
        check('deadline honoured', False, 'no exception')
    except OpenAICallFailed as error:
        check('deadline stops retries early',
              error.code == 'openai_timeout' and counter['attempts'] == 1,
              f"attempts={counter['attempts']}")


def test_guards(app, fixtures_dir):
    banner('OWL-9: input guards fail before spending anything')
    cases = [
        ('scanned.pdf.txt', 'no_text_extracted', 'scanned/image-only document'),
        ('empty.txt', 'no_text_extracted', 'empty file'),
        ('huge.txt', 'corpus_too_large', 'oversized corpus'),
    ]
    for index, (filename, expected_code, label) in enumerate(cases):
        chatbot_id, user_id = seed(app, fixtures_dir, [filename], 'terra', f'guard{index}')
        result = run_training(app, chatbot_id, user_id, timeout=120)
        artifact, path = artifact_of(chatbot_id)
        with app.app_context():
            from app import Chatbot, Document
            bot = Chatbot.query.get(chatbot_id)
            processed = [d.processed for d in Document.query.filter_by(chatbot_id=chatbot_id)]
        check(f'{label}: run failed with {expected_code}',
              result['status'] == 'failed' and result['error_code'] == expected_code,
              f"{result['status']}/{result['error_code']}")
        check(f'{label}: no artifact written', artifact is None)
        check(f'{label}: chatbot not marked trained', not bot.is_trained)
        check(f'{label}: documents not marked processed', not any(processed))
        check(f'{label}: zero tokens spent',
              (result['total_tokens'] or 0) == 0 and (result['embedding_tokens'] or 0) == 0)


def test_duplicate_click(app, fixtures_dir):
    banner('OWL-11: a second click attaches to the running run')
    from services import training_runner
    chatbot_id, user_id = seed(app, fixtures_dir, ['huge.txt'], 'terra', 'dupe')
    with app.app_context():
        first, created_first = training_runner.enqueue_training(app, chatbot_id, user_id)
        second, created_second = training_runner.enqueue_training(app, chatbot_id, user_id)
        same = first.run_id == second.run_id
    check('second enqueue returns the same run, not a duplicate',
          created_first and not created_second and same)


def test_reaper(app, fixtures_dir):
    banner('OWL-11: stale-run reaper')
    from app import db, TrainingRun
    from services import training_runner
    from datetime import datetime, timedelta
    import uuid

    chatbot_id, user_id = seed(app, fixtures_dir, ['small_faq.txt'], 'terra', 'reap')
    with app.app_context():
        stale = TrainingRun(run_id=uuid.uuid4().hex, chatbot_id=chatbot_id, user_id=user_id,
                            status='running', phase='kb_generating', progress=70,
                            host='some-dead-host:1',
                            created_at=datetime.utcnow() - timedelta(hours=2),
                            heartbeat_at=datetime.utcnow() - timedelta(hours=2))
        fresh = TrainingRun(run_id=uuid.uuid4().hex, chatbot_id=chatbot_id, user_id=user_id,
                            status='running', phase='embedding', progress=40,
                            host='some-other-host:2',
                            created_at=datetime.utcnow(), heartbeat_at=datetime.utcnow())
        db.session.add_all([stale, fresh])
        db.session.commit()
        stale_id, fresh_id = stale.run_id, fresh.run_id

        reaped = training_runner.reap_stale_runs(force=True)
        stale_after = TrainingRun.query.filter_by(run_id=stale_id).first()
        fresh_after = TrainingRun.query.filter_by(run_id=fresh_id).first()

    check('stale run marked orphaned',
          stale_after.status == 'orphaned' and stale_after.error_code == 'interrupted',
          f'{stale_after.status}/{stale_after.error_code}')
    check('a live run on another host is left alone', fresh_after.status == 'running')
    check('reaper reports what it reaped', reaped >= 1, f'reaped={reaped}')


def test_artifact_safety():
    banner('OWL-9: a failed write never damages the stored artifact')
    from services.chatbot_trainer import get_trainer
    from services.object_storage import PRIVATE, get_storage
    trainer = get_trainer()

    trainer._store_artifact(90001, {'schema_version': 3, 'kb_facts': [{'id': 'f0001'}],
                                    'qa_patterns': []})
    before = sha256_of(90001)

    class Unserializable:
        pass

    try:
        trainer._store_artifact(90001, {'bad': Unserializable()})
        check('unserializable payload raises', False, 'no exception')
    except Exception:
        check('unserializable payload raises', True)

    leftovers = [e['name'] for e in get_storage().list(PRIVATE, 'training/')
                 if '.tmp-' in e['name']]
    check('failed write leaves the stored artifact byte-identical',
          sha256_of(90001) == before)
    check('no temp objects left behind', not leftovers, str(leftovers))


def test_cache_invalidation():
    banner('Artifact cache is keyed on the training run id')
    from services.chatbot_trainer import get_trainer
    trainer = get_trainer()

    trainer._store_artifact(90002, {'schema_version': 3, 'kb_facts': [{'id': 'a'}],
                                    'qa_patterns': []}, run_id='run-A')
    first = trainer.get_training_data(90002, version='run-A')
    cached = trainer.get_training_data(90002, version='run-A')
    check('repeat reads at the same version are served from cache', first is cached)

    trainer._store_artifact(90002, {'schema_version': 3, 'kb_facts': [{'id': 'b'}],
                                    'qa_patterns': []}, run_id='run-B')
    check('a new run id refreshes the cache',
          trainer.get_training_data(90002, version='run-B')['kb_facts'][0]['id'] == 'b')
    check('an unversioned read never goes to the network',
          trainer.get_training_data(90002)['kb_facts'][0]['id'] == 'b')


def test_backward_compatibility():
    banner('Legacy and v1 artifacts still answer')
    from services.chatbot_trainer import get_trainer
    trainer = get_trainer()

    # legacy sentence format - never written again, but must still be read
    trainer._store_artifact(90003, {
        'sentences': ['Our office is at 44 Harbour Road.',
                      'The Starter plan is $49 per month.'],
        'legacy_format': True, 'embeddings': None})
    legacy = trainer.get_training_data(90003)
    hits = trainer.find_similar_content(90003, 'where is your office')
    check('legacy artifact is not treated as a knowledge base',
          not trainer.is_knowledge_base_format(legacy))
    check('legacy artifact still returns passages', bool(hits),
          hits[0]['content'][:40] if hits else 'none')

    # v1 knowledge base with no vector index (the KeyError case)
    trainer._store_artifact(90004, {
        'kb_facts': [{'id': 'f1', 'title': 'Business hours', 'keywords': ['hours'],
                      'answer_short': '9 to 5', 'answer_long': 'We are open 9am to 5pm.'}],
        'qa_patterns': []})
    v1 = trainer.get_training_data(90004)
    v1_hits = trainer.find_similar_content(90004, 'what are your business hours')
    check('v1 knowledge base is recognized', trainer.is_knowledge_base_format(v1))
    check('v1 knowledge base search does not raise KeyError', bool(v1_hits),
          v1_hits[0]['content'][:40] if v1_hits else 'none')
    check('v1 knowledge base has no vector index', not trainer.has_vector_index(v1))


# ----------------------------------------------------------------------
# Live tests
# ----------------------------------------------------------------------

def test_live_tiers(app, fixtures_dir):
    banner('OWL-13: live training across model tiers')
    from app import db, TokenUsage, Chatbot, Document

    for alias in ('luna', 'terra', 'sol'):
        chatbot_id, user_id = seed(app, fixtures_dir, ['small_faq.txt'], alias, f'live_{alias}')
        result = run_training(app, chatbot_id, user_id)
        if not check(f'{alias}: run succeeded', result['status'] == 'succeeded',
                     f"{result['status']}/{result['error_code']}: {result['error_message']}"):
            continue

        # The acceptance test for "training uses the per-chatbot model": this
        # used to read one global setting regardless of what the bot was set to.
        check(f'{alias}: trained on the chatbot\'s own tier',
              result['model_alias'] == alias, result['model_alias'])
        check(f'{alias}: progress reached 100', result['progress'] == 100)

        artifact, _path = artifact_of(chatbot_id)
        index = (artifact or {}).get('index') or {}
        check(f'{alias}: artifact is schema v3', artifact.get('schema_version') == 3)
        check(f'{alias}: extracted facts', len(artifact.get('kb_facts') or []) > 0,
              str(len(artifact.get('kb_facts') or [])))
        check(f'{alias}: index is internally consistent',
              index.get('count') == len(index.get('chunks') or [])
              == len(index.get('vectors_b64') or []) == result['chunk_count'],
              f"count={index.get('count')} run={result['chunk_count']}")

        from services.embedding_service import EmbeddingService
        vectors = EmbeddingService.decode_b64(index.get('vectors_b64'), index.get('dimensions'))
        norms = [sum(v * v for v in row) ** 0.5 for row in
                 (vectors.tolist() if hasattr(vectors, 'tolist') else vectors)]
        check(f'{alias}: vectors are 512-dim and normalized',
              index.get('dimensions') == 512 and all(abs(n - 1.0) < 1e-3 for n in norms),
              f'min_norm={min(norms):.4f}' if norms else 'none')

        with app.app_context():
            bot = Chatbot.query.get(chatbot_id)
            processed = [d.processed for d in Document.query.filter_by(chatbot_id=chatbot_id)]
            sources = {u.source: u.total_tokens for u in
                       TokenUsage.query.filter_by(user_id=user_id).all()}
        check(f'{alias}: chatbot marked trained with a timestamp',
              bot.is_trained and bot.last_trained_at is not None
              and bot.last_training_run_id == result['run_id'])
        check(f'{alias}: documents marked processed', all(processed))
        check(f'{alias}: training and embedding metered separately',
              sources.get('training', 0) > 0 and sources.get('embedding', 0) > 0,
              str(sources))

        # Retrieval actually answers from the documents.
        from services.chatbot_trainer import get_trainer
        with app.app_context():
            hits = get_trainer().search_chunks(chatbot_id, 'how much is the starter plan', top_k=3)
        check(f'{alias}: semantic search finds the pricing chunk',
              any('49' in h['content'] for h in hits),
              hits[0]['content'][:60] if hits else 'no hits')


def test_live_buried_fact(app, fixtures_dir):
    banner('OWL-10/13: the buried-fact test (multi-batch map-reduce)')
    chatbot_id, user_id = seed(app, fixtures_dir, ['handbook.txt'], 'terra', 'buried')
    result = run_training(app, chatbot_id, user_id)
    if not check('handbook run succeeded', result['status'] == 'succeeded',
                 f"{result['status']}/{result['error_code']}: {result['error_message']}"):
        return
    artifact, _path = artifact_of(chatbot_id)
    check('handbook produced multiple chunks', (result['chunk_count'] or 0) > 5,
          str(result['chunk_count']))

    from services.chatbot_trainer import get_trainer
    with app.app_context():
        hits = get_trainer().search_chunks(
            chatbot_id, 'what is the warranty escalation code for damaged servos', top_k=3)
    # This is the regression that the old whole-corpus-in-one-prompt design
    # could not pass: the fact sits in the middle of a long document.
    check('semantic search finds a fact buried mid-document',
          any('ZULU-774' in h['content'] for h in hits),
          hits[0]['content'][:80] if hits else 'no hits')


def test_live_preservation(app, fixtures_dir):
    banner('OWL-9 acceptance: a failed retrain preserves working training')
    from app import Chatbot
    from services.chatbot_trainer import get_trainer

    chatbot_id, user_id = seed(app, fixtures_dir, ['small_faq.txt'], 'terra', 'preserve')
    first = run_training(app, chatbot_id, user_id)
    if not check('baseline training succeeded', first['status'] == 'succeeded',
                 f"{first['status']}/{first['error_code']}"):
        return

    before = sha256_of(chatbot_id)

    # Break the credentials, exactly as a rotated/expired key would.
    trainer = get_trainer()
    embeddings = trainer.embeddings
    real_trainer_client, real_embed_client = trainer.openai_client, embeddings.client
    from openai import OpenAI
    trainer.openai_client = OpenAI(api_key='sk-invalid-key-for-qa', max_retries=0, timeout=30.0)
    embeddings.client = OpenAI(api_key='sk-invalid-key-for-qa', max_retries=0, timeout=30.0)
    embeddings._query_cache.clear()
    try:
        started = time.time()
        second = run_training(app, chatbot_id, user_id, timeout=120)
        elapsed = time.time() - started
    finally:
        trainer.openai_client, embeddings.client = real_trainer_client, real_embed_client

    with app.app_context():
        bot = Chatbot.query.get(chatbot_id)

    check('retrain with a bad key fails loudly',
          second['status'] == 'failed' and second['error_code'] == 'openai_auth',
          f"{second['status']}/{second['error_code']}")
    check('auth failure is fast (not retried)', elapsed < 60, f'{elapsed:.1f}s')
    check('the previous artifact is byte-identical', sha256_of(chatbot_id) == before)
    check('the chatbot is still marked trained', bot.is_trained)
    check('the failure has user-facing copy',
          bool(second['error_code']) and 'unchanged' in
          __import__('services.training_errors', fromlist=['x']).friendly_error(second['error_code']))


# ----------------------------------------------------------------------

SAMPLE_DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_docs')

# Every fixture in sample_docs/ carries a uniquely-worded fact so a live bot's
# answer can be asserted on an exact string. Here we only assert that the fact
# survives extraction - if it never reaches the chunker, no amount of model
# quality will put it in the knowledge base.
SAMPLE_FACTS = {
    'northwind_faq.txt': ['NW-4471', '2 business days'],
    'northwind_handbook.pdf': ['PX-820', '45 days'],
    'northwind_products.docx': ['Aurora burr grinder', '284.50'],
    'northwind_catalog.json': ['KL-9006'],
    'northwind_pricing.xlsx': ['18.75'],
}


def test_sample_docs():
    """Extraction of the sample corpus, including the PDF page-join regression.

    A PDF page join written as an escaped backslash-n instead of a real newline
    puts the two characters into the chunk text and the knowledge-base prompt,
    and hides the paragraph break from the chunker. It extracts without error,
    so only an assertion on the extracted text catches it.
    """
    banner('Sample training corpus: extraction and page joins')
    if not os.path.isdir(SAMPLE_DOCS):
        check('sample_docs/ exists', False, 'run: python sample_docs/generate.py')
        return

    from services.document_processor import DocumentProcessor

    literal_escape = chr(92) + 'n'
    processor = DocumentProcessor()
    for name, facts in SAMPLE_FACTS.items():
        path = os.path.join(SAMPLE_DOCS, name)
        if not os.path.exists(path):
            check(f'{name}: present', False, 'missing fixture')
            continue
        with open(path, 'rb') as handle:
            data = handle.read()
        text = processor.process_bytes(name, data)

        check(f'{name}: text extracted', len(text) > 200, f'{len(text)} chars')
        missing = [fact for fact in facts if fact not in text]
        check(f'{name}: seeded facts survive extraction', not missing,
              'missing: ' + ', '.join(missing) if missing else ', '.join(facts))
        check(f'{name}: no literal escaped newlines in the text',
              literal_escape not in text, f'{text.count(literal_escape)} found')
        check(f'{name}: process_bytes matches process_document',
              processor.process_document(path) == text)

    pdf_path = os.path.join(SAMPLE_DOCS, 'northwind_handbook.pdf')
    if os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as handle:
            pdf_text = processor.process_bytes('northwind_handbook.pdf', handle.read())
        check('multi-page PDF joins pages with real newlines',
              pdf_text.count(chr(10)) > 20, f'{pdf_text.count(chr(10))} newlines')


# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true',
                        help='also run real OpenAI training across all model tiers')
    args = parser.parse_args()

    fixtures_dir = os.path.join(SCRATCH, 'fixtures')
    write_fixtures(fixtures_dir)
    print(f'scratch: {SCRATCH}')

    app = make_app()

    test_sample_docs()
    test_retry_policy()
    test_artifact_safety()
    test_cache_invalidation()
    test_backward_compatibility()
    test_guards(app, fixtures_dir)
    test_duplicate_click(app, fixtures_dir)
    test_reaper(app, fixtures_dir)

    if args.live:
        if not os.getenv('OPENAI_API_KEY'):
            print('\n--live requires OPENAI_API_KEY; skipping live tests')
        else:
            test_live_tiers(app, fixtures_dir)
            test_live_buried_fact(app, fixtures_dir)
            test_live_preservation(app, fixtures_dir)

    banner('SUMMARY')
    failed = [name for name, passed, _detail in RESULTS if not passed]
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed')
    for name in failed:
        print(f'  FAILED: {name}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
