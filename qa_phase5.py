#!/usr/bin/env python3
"""Phase 5 QA: admin access to per-chatbot analytics (OWL-5 / OWL-6 / OWL-7).

Covers three things:

  * OWL-5  an admin can open any bot's analytics, and the token allowance /
           metering for that page follows the bot's OWNER, not the viewer.
  * OWL-6  the admin chatbots list and the admin chatbot detail page both link
           to it.
  * OWL-7  a regular user still cannot see anyone else's analytics, and the
           refusal looks identical to asking for a bot that does not exist.

Runs entirely offline against a throwaway SQLite file: storage is forced to the
local backend and AnalyticsService._extract_keywords_ai is replaced with a spy,
so no OpenAI call is made and the suite costs nothing. The spy also records the
allow_ai flag it was handed, which is how the owner-vs-viewer allowance rule is
asserted without spending real tokens.
"""
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix='owlbee_p5_')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(SCRATCH, 'qa.db').replace(os.sep, '/')
os.environ['LOCAL_STORAGE_PUBLIC_DIR'] = os.path.join(SCRATCH, 'pub')
os.environ['LOCAL_STORAGE_PRIVATE_DIR'] = os.path.join(SCRATCH, 'priv')
os.environ['LOG_LEVEL'] = 'WARNING'
# Same guard as qa_phase4_app.py: set to empty rather than deleted, because
# app.py calls load_dotenv() and a deleted key would be repopulated from .env,
# silently pointing this suite at the real Bunny zones.
for _k in ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ZONE', 'BUNNY_PUBLIC_ACCESS_KEY',
           'BUNNY_PUBLIC_CDN_URL', 'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY',
           'BUNNY_STORAGE_HOST_PRIVATE'):
    os.environ[_k] = ''

from app import (create_app, db, User, Chatbot, Conversation, Plan, UserSubscription,
                 TokenUsage, current_period_key)
from werkzeug.security import generate_password_hash
from services.analytics_service import AnalyticsService

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  [{detail}]' if detail else ''))


# ------------------------------------------------------------------ AI stub
# Replaces the one call on this page that would hit OpenAI. Records what it was
# asked to do so the tests can assert on it, and reports a token spend so the
# metering path is exercised end to end.
ai_calls = []


def _fake_extract_keywords(self, messages, max_keywords=20, usage_sink=None, allow_ai=True):
    ai_calls.append({'allow_ai': allow_ai, 'messages': len(messages)})
    if allow_ai and usage_sink is not None:
        usage_sink.append({'prompt_tokens': 30, 'completion_tokens': 12, 'total_tokens': 42})
    return [{'keyword': 'pricing', 'score': 85}]


AnalyticsService._extract_keywords_ai = _fake_extract_keywords

app = create_app()

# ------------------------------------------------------------------ fixtures
with app.app_context():
    capped = Plan(name='P5 Capped', description='qa', monthly_price=0, yearly_price=0,
                  chatbot_limit=9, file_size_limit_mb=20,
                  allowed_models=json.dumps(['luna']), monthly_token_limit=1000,
                  web_search_enabled=False, is_active=True)
    db.session.add(capped)
    db.session.commit()

    owner = User(username='p5owner', email='p5owner@example.com',
                 password_hash=generate_password_hash('pw'))
    stranger = User(username='p5stranger', email='p5stranger@example.com',
                    password_hash=generate_password_hash('pw'))
    admin = User(username='p5admin', email='p5admin@example.com',
                 password_hash=generate_password_hash('pw'), is_admin=True)
    db.session.add_all([owner, stranger, admin])
    db.session.commit()
    db.session.add(UserSubscription(user_id=owner.id, plan_id=capped.id, status='active',
                                    created_at=datetime.utcnow()))

    bot = Chatbot(name='Owner Bot', url_name='owner-bot', description='qa',
                  embed_code=str(uuid.uuid4()), user_id=owner.id, model_alias='luna')
    stranger_bot = Chatbot(name='Stranger Bot', url_name='stranger-bot', description='qa',
                           embed_code=str(uuid.uuid4()), user_id=stranger.id, model_alias='luna')
    db.session.add_all([bot, stranger_bot])
    db.session.commit()

    for i in range(3):
        db.session.add(Conversation(
            chatbot_id=bot.id, user_message=f'What does the Starter plan cost? ({i})',
            bot_response='Forty-nine dollars a month.', response_status='resolved',
            timestamp=datetime.utcnow() - timedelta(days=i)))
    db.session.commit()

    owner_id, stranger_id, admin_id = owner.id, stranger.id, admin.id
    bot_id, stranger_bot_id = bot.id, stranger_bot.id
    missing_bot_id = bot_id + 10_000


def client_for(user_id):
    c = app.test_client()
    if user_id is not None:
        with c.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
    return c


owner_client = client_for(owner_id)
stranger_client = client_for(stranger_id)
admin_client = client_for(admin_id)
anon_client = client_for(None)

ANALYTICS = f'/chatbot/{bot_id}/analytics'

# --------------------------------------------------------- OWL-5: admin access
print('\nOWL-5  analytics route accepts admin viewers')

resp = owner_client.get(ANALYTICS)
check('owner still gets their own analytics', resp.status_code == 200, str(resp.status_code))
owner_html = resp.get_data(as_text=True)
check('owner page renders the metrics', 'Total Interactions' in owner_html)
check('owner page is not flagged as an admin view',
      'user-shield' not in owner_html and 'Back to Admin View' not in owner_html)

resp = admin_client.get(ANALYTICS)
check('admin gets another user\'s analytics', resp.status_code == 200, str(resp.status_code))
admin_html = resp.get_data(as_text=True)
check('admin page renders the same metrics', 'Total Interactions' in admin_html)
check('admin page names the owner', 'p5owner' in admin_html)
check('admin page links back to the admin view of the bot',
      f'/admin/chatbots/{bot_id}' in admin_html and 'Back to Admin View' in admin_html)

resp = admin_client.get(f'/chatbot/{missing_bot_id}/analytics')
check('admin still gets 404 for a chatbot that does not exist',
      resp.status_code == 404, str(resp.status_code))

# ------------------------------------------- OWL-5: allowance follows the owner
print('\nOWL-5  token allowance and metering follow the bot owner')

ai_calls.clear()
admin_client.get(ANALYTICS)
check('keyword extraction ran for the admin view', len(ai_calls) == 1, str(len(ai_calls)))
check('owner under their cap => AI keywords allowed',
      ai_calls and ai_calls[0]['allow_ai'] is True)

with app.app_context():
    rows = TokenUsage.query.filter_by(period_key=current_period_key(),
                                      source='analytics').all()
    billed = {(r.user_id, r.chatbot_id): r.total_tokens for r in rows}
check('analytics spend is billed to the owner, not the admin',
      billed.get((owner_id, bot_id), 0) > 0 and not any(uid == admin_id for uid, _ in billed),
      str(billed))

# Push the OWNER over their 1000-token cap. The admin's own plan is unlimited,
# so if the route read current_user the AI call would still be allowed here -
# that is exactly the bug this asserts against.
with app.app_context():
    db.session.add(TokenUsage(user_id=owner_id, chatbot_id=bot_id,
                              period_key=current_period_key(), source='chat',
                              prompt_tokens=0, completion_tokens=0, total_tokens=5000,
                              request_count=1, blocked_count=0))
    db.session.commit()

ai_calls.clear()
resp = admin_client.get(ANALYTICS)
check('admin page still renders when the owner is over quota',
      resp.status_code == 200, str(resp.status_code))
check('owner over their cap => AI keywords skipped for the admin viewer too',
      ai_calls and ai_calls[0]['allow_ai'] is False,
      str(ai_calls))

ai_calls.clear()
owner_client.get(ANALYTICS)
check('owner over their cap => AI keywords skipped for the owner as well',
      ai_calls and ai_calls[0]['allow_ai'] is False, str(ai_calls))

# ------------------------------------------------------- OWL-6: the admin links
print('\nOWL-6  analytics links are present in the admin area')

resp = admin_client.get('/admin/chatbots')
check('admin chatbots list loads', resp.status_code == 200, str(resp.status_code))
list_html = resp.get_data(as_text=True)
check('admin chatbots list links to analytics for the owner\'s bot',
      f'/chatbot/{bot_id}/analytics' in list_html)
check('admin chatbots list links to analytics for every bot',
      f'/chatbot/{stranger_bot_id}/analytics' in list_html)

resp = admin_client.get(f'/admin/chatbots/{bot_id}')
check('admin chatbot detail page loads', resp.status_code == 200, str(resp.status_code))
detail_html = resp.get_data(as_text=True)
check('admin chatbot detail page has an Analytics button',
      f'/chatbot/{bot_id}/analytics' in detail_html and '>Analytics' in detail_html.replace('\n', ''))

# ------------------------------------------------- OWL-7: non-admins stay locked
print('\nOWL-7  regular users still cannot see other users\' analytics')

resp = stranger_client.get(ANALYTICS)
check('a logged-in non-owner gets 404, not the page',
      resp.status_code == 404, str(resp.status_code))
body = resp.get_data(as_text=True)
check('the refusal leaks no analytics content',
      'Total Interactions' not in body and 'Starter plan' not in body)
check('the refusal leaks no owner identity', 'p5owner' not in body)

resp_missing = stranger_client.get(f'/chatbot/{missing_bot_id}/analytics')
check('a non-existent bot answers the same way as someone else\'s bot',
      resp_missing.status_code == resp.status_code,
      f'{resp_missing.status_code} vs {resp.status_code}')

resp = stranger_client.get(f'/chatbot/{stranger_bot_id}/analytics')
check('a non-owner can still see their OWN bot\'s analytics',
      resp.status_code == 200, str(resp.status_code))

resp = anon_client.get(ANALYTICS)
check('anonymous visitors are bounced to login, never served the page',
      resp.status_code in (301, 302) and 'login' in resp.headers.get('Location', '').lower(),
      f"{resp.status_code} -> {resp.headers.get('Location')}")

resp = stranger_client.get(f'/admin/chatbots/{bot_id}')
check('a non-admin still cannot reach the admin chatbot page',
      resp.status_code in (301, 302) and 'admin/login' in resp.headers.get('Location', ''),
      f"{resp.status_code} -> {resp.headers.get('Location')}")

# Promoting the stranger flips access on with nothing else changing, which shows
# the gate is is_admin and not some incidental property of the seeded admin.
with app.app_context():
    User.query.get(stranger_id).is_admin = True
    db.session.commit()
resp = client_for(stranger_id).get(ANALYTICS)
check('the gate is is_admin: promoting the same user grants access',
      resp.status_code == 200, str(resp.status_code))
with app.app_context():
    User.query.get(stranger_id).is_admin = False
    db.session.commit()
resp = client_for(stranger_id).get(ANALYTICS)
check('demoting the same user takes access away again',
      resp.status_code == 404, str(resp.status_code))

failed = [n for n, ok in results if not ok]
print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
for name in failed:
    print('  FAILED:', name)
sys.exit(1 if failed else 0)
