#!/usr/bin/env python3
"""Full app flow against the REAL Bunny zones: upload -> train -> chat -> delete.

    python qa_phase4_live_app.py

Needs the BUNNY_* credentials and an OPENAI_API_KEY (it runs one real training
job). Uses a scratch SQLite database - the live Postgres is never touched - and
removes every object it creates. This is the run that proves production
readiness, including that /uploads 302s to the CDN and that an anonymous browser
on a customer's site can fetch the avatar.
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

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

SCRATCH = tempfile.mkdtemp(prefix='owlbee_live_e2e_')
# Scratch database. The live Postgres is never touched by this script.
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(SCRATCH, 'qa.db').replace(os.sep, '/')
os.environ['LOG_LEVEL'] = 'WARNING'

import requests
import services.object_storage as st
from app import (create_app, db, User, Chatbot, Document, Plan, UserSubscription,
                 Settings, TRAINING_TERMINAL_STATUSES)
from werkzeug.security import generate_password_hash

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  [{detail}]' if detail else ''))


app = create_app()
backend = st.get_storage()
print('backend:', backend.name, '| public zone:', backend.zones[st.PUBLIC].zone_name)
assert backend.name == 'bunny', 'this test requires the Bunny backend'

created_objects = []

with app.app_context():
    plan = Plan(name='LiveE2E', monthly_price=0, yearly_price=0, chatbot_limit=9,
                file_size_limit_mb=20, allowed_models=json.dumps(['luna']),
                monthly_token_limit=None, web_search_enabled=False, is_active=True)
    db.session.add(plan)
    db.session.commit()
    db.session.add(Settings(key='training_prompt', value=(
        '{base_prompt}\n\nUse the following information from the training documents '
        'to answer the user. If it is not there, say you do not have it.\n\n{context}')))
    user = User(username='livee2e', email='livee2e@example.com',
                password_hash=generate_password_hash('pw'))
    db.session.add(user)
    db.session.commit()
    db.session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status='active',
                                    created_at=datetime.utcnow()))
    bot = Chatbot(name='Live E2E Bot', description='qa', embed_code=str(uuid.uuid4()),
                  user_id=user.id, model_alias='luna')
    db.session.add(bot)
    db.session.commit()
    bot_id, user_id, embed_code = bot.id, user.id, bot.embed_code

client = app.test_client()
with client.session_transaction() as sess:
    sess['_user_id'] = str(user_id)
    sess['_fresh'] = True

try:
    # ---------------------------------------------------------- document
    text = ('Acme hours are 9am to 5pm. The Starter plan costs $49 per month. '
            'Our office is at 44 Harbour Road, Portland. ' * 8)
    resp = client.post(f'/upload_document/{bot_id}',
                       data={'file': (_io.BytesIO(text.encode()), 'live_faq.txt')},
                       content_type='multipart/form-data',
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    check('document uploads to Bunny', resp.status_code == 200
          and (resp.get_json() or {}).get('success'), str(resp.get_json())[:80])

    with app.app_context():
        doc = Document.query.filter_by(chatbot_id=bot_id).first()
        doc_key, doc_id = doc.storage_key, doc.id
    created_objects.append((st.PRIVATE, doc_key))
    check('object is in the private zone', backend.exists(st.PRIVATE, doc_key), doc_key)

    resp = client.get(f'/download_document/{doc_id}')
    check('download proxies the bytes back',
          resp.status_code == 200 and resp.get_data() == text.encode(),
          f'{resp.status_code}, {len(resp.get_data())} bytes')

    # ---------------------------------------------------------- training
    resp = client.post(f'/train_chatbot/{bot_id}',
                       headers={'X-Requested-With': 'XMLHttpRequest'})
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
        time.sleep(2)
    check('training completes', final and final['status'] == 'succeeded',
          f"{(final or {}).get('status')}/{(final or {}).get('error_message')}")

    artifact = f'training/chatbot_{bot_id}.json'
    created_objects.append((st.PRIVATE, artifact))
    info = backend.stat(st.PRIVATE, artifact)
    check('knowledge base is in the private zone', bool(info),
          f"{info['bytes']:,} bytes" if info else 'absent')

    # ---------------------------------------------------------- chat
    resp = client.post(f'/api/chat/{embed_code}',
                       json={'message': 'how much does the starter plan cost?'})
    body = resp.get_json() or {}
    check('chat answers from the stored knowledge base',
          '49' in (body.get('response') or ''), (body.get('response') or '')[:70])

    # ---------------------------------------------------------- avatar + CDN
    png = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 4
    client.post(f'/chatbot/{bot_id}/update', data={
        'name': 'Live E2E Bot', 'description': 'qa', 'system_prompt': 'be helpful',
        'model_alias': 'luna', 'avatar': (_io.BytesIO(png), 'logo.png')},
        content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        avatar_name = Chatbot.query.get(bot_id).avatar_filename
    check('avatar uploaded', bool(avatar_name), str(avatar_name))

    if avatar_name:
        created_objects.append((st.PUBLIC, st.avatar_key(avatar_name)))
        resp = client.get(f'/uploads/{avatar_name}')
        location = resp.headers.get('Location', '')
        check('/uploads 302s to the CDN (never 301)',
              resp.status_code == 302 and location.startswith('https://'),
              f'{resp.status_code} -> {location[:60]}')
        check('redirect is cacheable but not permanent',
              'max-age' in (resp.headers.get('Cache-Control') or ''),
              resp.headers.get('Cache-Control'))

        # Follow it exactly as a browser on a customer's site would.
        fetched = None
        for _ in range(4):
            cdn_response = requests.get(location, timeout=20)
            if cdn_response.status_code == 200:
                fetched = cdn_response.content
                break
            time.sleep(3)
        check('the CDN serves the avatar bytes to an anonymous browser',
              fetched == png,
              f'{len(fetched) if fetched else 0} bytes vs {len(png)}')

        with app.test_request_context():
            from flask import current_app
            embed_url = current_app.jinja_env.globals['get_avatar_embed_url'](avatar_name)
        check('embed snippet URL is absolute with exactly one scheme',
              embed_url.count('://') == 1, embed_url)
        check('embed snippet URL points at the CDN',
              embed_url.startswith(backend.zones[st.PUBLIC].cdn_base_url), embed_url)

    # ---------------------------------------------------------- cleanup path
    resp = client.post(f'/delete_chatbot/{bot_id}', follow_redirects=True)
    check('deleting the chatbot removes its objects',
          resp.status_code == 200
          and not backend.exists(st.PRIVATE, doc_key)
          and not backend.exists(st.PRIVATE, artifact)
          and (not avatar_name or not backend.exists(st.PUBLIC, st.avatar_key(avatar_name))))

finally:
    leftovers = 0
    for zone, key in created_objects:
        try:
            if backend.delete(zone, key):
                leftovers += 1
        except Exception as error:
            print(f'  (cleanup failed for {zone}:{key}: {error})')
    print(f'\ncleanup: removed {leftovers} object(s) the app had not already deleted')

print('=' * 60)
failed = [n for n, ok in results if not ok]
print(f'{len(results) - len(failed)}/{len(results)} live end-to-end checks passed')
for name in failed:
    print('  FAILED:', name)
sys.exit(1 if failed else 0)
