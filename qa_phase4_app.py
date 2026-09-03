#!/usr/bin/env python3
"""Phase 4 app-level QA: upload -> train -> chat -> download -> delete.

Exercises the whole request path against the LOCAL storage backend, so it needs
no Bunny credentials and costs nothing but an OpenAI training run. Run
qa_phase4.py for the storage client itself, and qa_phase4.py --live for real
round trips against the configured zones.
"""
import io as _io
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix='owlbee_p4routes_')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(SCRATCH, 'qa.db').replace(os.sep, '/')
os.environ['LOCAL_STORAGE_PUBLIC_DIR'] = os.path.join(SCRATCH, 'pub')
os.environ['LOCAL_STORAGE_PRIVATE_DIR'] = os.path.join(SCRATCH, 'priv')
os.environ['LOG_LEVEL'] = 'WARNING'
# Force the local backend. Setting these to empty rather than deleting them is
# deliberate: app.py calls load_dotenv(), which does not override a key already
# present in the environment but would happily repopulate a deleted one from
# .env - silently running this suite against the real Bunny zones.
for _k in ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ZONE', 'BUNNY_PUBLIC_ACCESS_KEY',
           'BUNNY_PUBLIC_CDN_URL', 'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY',
           'BUNNY_STORAGE_HOST_PRIVATE'):
    os.environ[_k] = ''

from app import (create_app, db, User, Chatbot, Document, Plan, UserSubscription,
                 Settings, TrainingRun, TRAINING_TERMINAL_STATUSES)
from werkzeug.security import generate_password_hash
import services.object_storage as st
from services.chatbot_trainer import get_trainer, artifact_version

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  [{detail}]' if detail else ''))


app = create_app()

assert st.get_storage().name == 'local', (
    'this suite must run on the local backend; got '
    + st.get_storage().name + '. Use qa_phase4_live_app.py for Bunny.')

with app.app_context():
    plan = Plan(name='P4QA', description='qa', monthly_price=0, yearly_price=0,
                chatbot_limit=9, file_size_limit_mb=20,
                allowed_models=json.dumps(['luna', 'terra', 'sol']),
                monthly_token_limit=None, web_search_enabled=False, is_active=True)
    db.session.add(plan)
    db.session.commit()
    db.session.add(Settings(key='training_prompt', value=(
        '{base_prompt}\n\n'
        'Use the following information from the training documents to answer the user. '
        'If the answer is not present, say you do not have that information.\n\n'
        '{context}')))
    user = User(username='p4qa', email='p4qa@example.com',
                password_hash=generate_password_hash('pw'))
    db.session.add(user)
    db.session.commit()
    db.session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status='active',
                                    created_at=datetime.utcnow()))
    bot = Chatbot(name='P4 Bot', description='qa', embed_code=str(uuid.uuid4()),
                  user_id=user.id, model_alias='luna')
    db.session.add(bot)
    db.session.commit()
    bot_id, user_id, embed_code = bot.id, user.id, bot.embed_code

client = app.test_client()
with client.session_transaction() as sess:
    sess['_user_id'] = str(user_id)
    sess['_fresh'] = True

# ---------------------------------------------------------------- upload
doc_text = ('Acme hours are 9am to 5pm. The Starter plan costs $49 per month. '
            'Our office is at 44 Harbour Road, Portland. ' * 8)
resp = client.post(f'/upload_document/{bot_id}',
                   data={'file': (_io.BytesIO(doc_text.encode()), 'faq.txt')},
                   content_type='multipart/form-data',
                   headers={'X-Requested-With': 'XMLHttpRequest'})
check('upload returns success', resp.status_code == 200 and resp.get_json().get('success'),
      str(resp.get_json())[:100])

with app.app_context():
    doc = Document.query.filter_by(chatbot_id=bot_id).first()
    key = doc.storage_key if doc else None
check('document row carries a storage key', bool(key), str(key))
check('storage key is sharded by chatbot', key and key.startswith(f'documents/{bot_id}/'), str(key))
check('legacy file_path is not written', doc.file_path == '', repr(doc.file_path))
check('object exists in the private zone', st.get_storage().exists(st.PRIVATE, key))
check('object is byte-identical',
      st.get_storage().get(st.PRIVATE, key).decode() == doc_text)

# ---------------------------------------------------------------- download
resp = client.get(f'/download_document/{doc.id}')
check('download returns the bytes', resp.status_code == 200 and resp.get_data() == doc_text.encode(),
      f'{resp.status_code}, {len(resp.get_data())} bytes')
check('download is not a redirect (private zone stays behind auth)',
      resp.status_code != 302)

# ---------------------------------------------------------------- train
resp = client.post(f'/train_chatbot/{bot_id}', headers={'X-Requested-With': 'XMLHttpRequest'})
run_id = (resp.get_json() or {}).get('run_id')
check('training starts', resp.status_code == 202 and bool(run_id), str(resp.status_code))

final = None
deadline = time.time() + 300
while time.time() < deadline:
    payload = client.get(f'/train_chatbot/{bot_id}/status?run_id={run_id}').get_json()
    run = (payload or {}).get('run') or {}
    if run.get('terminal'):
        final = run
        break
    time.sleep(1)
check('training reaches a terminal state', final is not None)
if final:
    check('training succeeded', final['status'] == 'succeeded',
          f"{final['status']}/{final.get('error_code')}: {final.get('error_message')}")

artifact = f'training/chatbot_{bot_id}.json'
check('artifact is in the private zone', st.get_storage().exists(st.PRIVATE, artifact))
check('no temp artifacts left behind',
      not [e for e in st.get_storage().list(st.PRIVATE, 'training/') if '.tmp-' in e['name']])

# ---------------------------------------------------------------- cache
with app.app_context():
    bot = Chatbot.query.get(bot_id)
    version = artifact_version(bot)
    trainer = get_trainer()

    calls = {'n': 0}
    real_get = st.get_storage().get

    def counting_get(zone, key, **kw):
        calls['n'] += 1
        return real_get(zone, key, **kw)

    st.get_storage().get = counting_get
    try:
        trainer.prime(bot_id, version)
        after_prime = calls['n']
        trainer.get_training_data(bot_id, version=version)
        trainer.get_training_data(bot_id)
        trainer.get_training_data(bot_id, version=version)
        after_reads = calls['n']
        # A retrain changes the version, which must force a refetch.
        trainer.get_training_data(bot_id, version='some-other-run')
        after_new_version = calls['n']
    finally:
        st.get_storage().get = real_get

check('write-through means prime after training costs no fetch', after_prime == 0,
      f'{after_prime} fetches')
check('repeat reads make zero storage calls', after_reads == after_prime,
      f'{after_reads - after_prime} extra fetches')
check('a new version forces a refetch', after_new_version == after_reads + 1,
      f'{after_new_version - after_reads} fetches')

# ---------------------------------------------------------------- chat
resp = client.post(f'/api/chat/{embed_code}',
                   json={'message': 'how much does the starter plan cost?'})
body = resp.get_json() or {}
check('chat answers', resp.status_code == 200 and bool(body.get('response')), str(body)[:90])
check('answer uses the trained document', '49' in (body.get('response') or ''),
      (body.get('response') or '')[:80])

# ---------------------------------------------------------------- avatars
png = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 64)
resp = client.post(f'/chatbot/{bot_id}/update', data={
    'name': 'P4 Bot', 'description': 'qa', 'system_prompt': 'be helpful',
    'model_alias': 'luna',
    'avatar': (_io.BytesIO(png), 'face.png'),
}, content_type='multipart/form-data', follow_redirects=True)
with app.app_context():
    avatar_name = Chatbot.query.get(bot_id).avatar_filename
check('avatar upload stored a filename', bool(avatar_name), str(avatar_name))
if avatar_name:
    check('avatar object is in the public zone',
          st.get_storage().exists(st.PUBLIC, f'avatars/{avatar_name}'))
    resp = client.get(f'/uploads/{avatar_name}')
    check('/uploads serves the avatar on the local backend',
          resp.status_code == 200 and resp.get_data() == png, str(resp.status_code))

resp = client.get('/uploads/../../app.py')
check('/uploads rejects traversal', resp.status_code in (404, 308), str(resp.status_code))
resp = client.get('/uploads/does-not-exist.png')
check('/uploads 404s an unknown avatar', resp.status_code == 404, str(resp.status_code))

# ---------------------------------------------------------------- avatar URL helpers
with app.test_request_context():
    from flask import current_app
    rel = current_app.jinja_env.globals['get_avatar_url'](avatar_name)
    absolute = current_app.jinja_env.globals['get_avatar_embed_url'](avatar_name)
check('get_avatar_url stays relative (embed snippet prepends the origin)',
      rel and '://' not in rel, str(rel))
check('get_avatar_embed_url is absolute with exactly one scheme',
      absolute and absolute.count('://') == 1, str(absolute))

# ---------------------------------------------------------------- health
health = client.get('/health').get_json()
storage_info = (health or {}).get('storage') or {}
check('health reports the backend', storage_info.get('backend') == 'local',
      str(storage_info.get('backend')))
check('health makes no network call by default', 'probe' not in storage_info)

# ---------------------------------------------------------------- delete
resp = client.post(f'/delete_chatbot/{bot_id}', follow_redirects=True)
check('delete succeeds', resp.status_code == 200, str(resp.status_code))
check('document object removed', not st.get_storage().exists(st.PRIVATE, key))
check('artifact removed', not st.get_storage().exists(st.PRIVATE, artifact))
if avatar_name:
    check('avatar object removed',
          not st.get_storage().exists(st.PUBLIC, f'avatars/{avatar_name}'))
with app.app_context():
    check('training runs removed', TrainingRun.query.filter_by(chatbot_id=bot_id).count() == 0)

print('\n' + '=' * 60)
# ------------------------------------------------- extraction parity
# process_bytes() must equal process_document() exactly. Serving documents out
# of object storage with no temp file on the way in rests entirely on this.
from services.document_processor import DocumentProcessor
import glob

processor = DocumentProcessor()
parity_files = []

txt_path = os.path.join(SCRATCH, 'p.txt')
with open(txt_path, 'w', encoding='utf-8') as fh:
    fh.write('Acme hours are 9am to 5pm. The Starter plan costs $49.')
parity_files.append(txt_path)

json_path = os.path.join(SCRATCH, 'p.json')
with open(json_path, 'w', encoding='utf-8') as fh:
    json.dump({'plans': [{'name': 'Starter', 'price': 49}], 'hours': '9-5'}, fh)
parity_files.append(json_path)

# A real multi-page PDF beats a synthesized one.
parity_files.extend(glob.glob('uploads/*.pdf')[:1])

for path in parity_files:
    with open(path, 'rb') as fh:
        raw = fh.read()
    try:
        same = (processor.process_document(path)
                == processor.process_bytes(os.path.basename(path), raw))
        detail = ''
    except Exception as exc:
        same, detail = False, f'{type(exc).__name__}: {exc}'
    check(f'process_bytes matches process_document for {os.path.basename(path)}',
          same, detail)

failed = [n for n, ok in results if not ok]
print(f'{len(results) - len(failed)}/{len(results)} route checks passed')
for name in failed:
    print('  FAILED:', name)
sys.exit(1 if failed else 0)
