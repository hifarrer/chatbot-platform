#!/usr/bin/env python3
"""Phase 6 QA: chatbot replies must reach the browser as well-formed HTML.

The bug this guards against, in full. The owner-facing chat ran
formatTextForChat() over the reply and *then* ran a link regex over the result.
formatBoldText bolded plan names with /\\b(Free|Starter|...)\\b/gi, a hyphen is a
word boundary, so `free` inside

    https://smallscholars.com.au/free-trial-enquiries/

matched and a <strong class="text-primary"> landed in the middle of the URL.
The link regex - https?://[^\\s]+, greedy to the first space, now the space
inside that tag - then wrapped half a tag in an anchor, and the visitor saw

    You can also book online here: https://smallscholars.com.au/ class="text-primary">free-trial-enquiries/

An October 2025 fix reordered the email/phone/URL passes in all four copies of
that function and did not help, because the ordering was never the problem.

So this suite asserts three separate things:

  * services/reply_sanitizer.py repairs, allowlists and linkifies correctly, and
    is idempotent - double-processing is precisely what caused the bug.
  * POST /api/chat/<embed_code> returns both a plain-text `response` and a
    sanitized `response_html`, and still stores the RAW model text in
    Conversation.bot_response (that column is the audit record).
  * No copy of the old client-side link regex has come back, and the two copies
    of the shared JS helper have not drifted apart. There is no build step in
    this project, so a failing assertion is the only honest drift guard.

Runs entirely offline against a throwaway SQLite file - no OpenAI call, no
network, no cost. On Windows run it with PYTHONUTF8=1: emoji prints in the chat
route crash on a cp1252 console.
"""
import io
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix='owlbee_p6_')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(SCRATCH, 'qa.db').replace(os.sep, '/')
os.environ['LOCAL_STORAGE_PUBLIC_DIR'] = os.path.join(SCRATCH, 'pub')
os.environ['LOCAL_STORAGE_PRIVATE_DIR'] = os.path.join(SCRATCH, 'priv')
os.environ['LOG_LEVEL'] = 'WARNING'
# Same guard as qa_phase5.py: set to empty rather than deleted, because app.py
# calls load_dotenv() and a deleted key would be repopulated from .env,
# silently pointing this suite at the real Bunny zones.
for _k in ('BUNNY_STORAGE_HOST', 'BUNNY_PUBLIC_ZONE', 'BUNNY_PUBLIC_ACCESS_KEY',
           'BUNNY_PUBLIC_CDN_URL', 'BUNNY_PRIVATE_ZONE', 'BUNNY_PRIVATE_ACCESS_KEY',
           'BUNNY_STORAGE_HOST_PRIVATE'):
    os.environ[_k] = ''
# Same trick, and it is load-bearing here: get_chat_service() is a closure
# inside create_app(), so it cannot be monkeypatched from out here. An empty key
# makes ChatServiceOpenAI() raise, get_chat_service() return None, and the route
# fall through to the local ChatService that this suite stubs. Without it the
# suite quietly bills a real OpenAI call on every run.
os.environ['OPENAI_API_KEY'] = ''

from services.reply_sanitizer import (MAX_REPLY_CHARS, reply_to_plain_text,
                                      sanitize_reply)

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  [{detail}]' if detail else ''))


# The exact reply from the bug report.
REPORTED = ('You can also book online here: '
            '<a href="https://smallscholars.com.au/free-trial-enquiries/" '
            'class="text-primary">Book now</a>')
REPORTED_PLAIN = ('You can also book online here: '
                  'https://smallscholars.com.au/free-trial-enquiries/')
# What the browser actually rendered before the fix.
LEAKED = 'class="text-primary">free-trial-enquiries/'

# ------------------------------------------------------- the reported failure
print('\nThe reported failure')

out = sanitize_reply(REPORTED)
check('reported reply keeps exactly one anchor', out.count('<a ') == 1, out)
check('reported reply keeps the full href',
      'href="https://smallscholars.com.au/free-trial-enquiries/"' in out)
check('reported reply keeps the customer class', 'class="text-primary"' in out)
check('reported reply does not leak the attribute as text', LEAKED not in out, out)
check('reported reply is not double-escaped', '&lt;a' not in out)

out = sanitize_reply(REPORTED_PLAIN)
check('same URL as bare text linkifies once', out.count('<a ') == 1, out)
check('bare URL keeps every path segment',
      'https://smallscholars.com.au/free-trial-enquiries/' in out, out)
check('bare URL does not leak a tag into the href', '<strong' not in out, out)

# ------------------------------------------------------------------ repair
print('\nMalformed markup is repaired')

check('unclosed tag is closed', sanitize_reply('<b>Hello', linkify=False) == '<b>Hello</b>',
      sanitize_reply('<b>Hello', linkify=False))
check('stray end tag is dropped', sanitize_reply('</div>stray') == 'stray',
      sanitize_reply('</div>stray'))

nested = sanitize_reply('<a href="https://a.test/">one <a href="https://b.test/">two</a></a>')
check('nested anchors collapse to one', nested.count('<a ') == 1, nested)
check('nested anchor text survives', 'one two' in nested, nested)

unwrapped = sanitize_reply('<div class="wrapper">hi</div>')
check('unknown tag is unwrapped, text kept', unwrapped == 'hi', unwrapped)

# ---------------------------------------------------------------- injection
print('\nInjection is stripped')

for label, payload in [
    ('javascript: href', '<a href="javascript:alert(1)">click</a>'),
    ('entity-obfuscated', '<a href="&#106;avascript:alert(1)">click</a>'),
    ('tab-obfuscated', '<a href="java\tscript:alert(1)">click</a>'),
    ('data: href', '<a href="data:text/html;base64,PHNjcmlwdD4=">click</a>'),
]:
    out = sanitize_reply(payload)
    check(f'{label} produces no link', '<a' not in out, out)
    check(f'{label} keeps the link text', 'click' in out, out)
    check(f'{label} leaves no scheme behind',
          'javascript' not in out.lower() and 'data:' not in out.lower(), out)

out = sanitize_reply('Hi<script>alert(document.cookie)</script>')
check('script tag is gone', '<script' not in out.lower(), out)
check('script PAYLOAD is gone too, not just unwrapped', 'alert(' not in out, out)
check('surrounding text survives', 'Hi' in out, out)

check('event handler attribute is stripped',
      sanitize_reply('<b onclick="alert(1)">hi</b>', linkify=False) == '<b>hi</b>',
      sanitize_reply('<b onclick="alert(1)">hi</b>', linkify=False))

out = sanitize_reply('<img src=x onerror=alert(1)>')
check('img is dropped entirely', '<img' not in out and 'onerror' not in out, repr(out))

out = sanitize_reply('<b style="position:fixed">hi</b>', linkify=False)
check('style attribute is stripped', 'style' not in out, out)

out = sanitize_reply('<a href="//evil.test/x">click</a>')
check('protocol-relative href is refused', '<a' not in out, out)

# --------------------------------------------------------------- linkifying
print('\nLinkifying, over text only')

out = sanitize_reply('Visit smallscholars.com.au for details')
check('bare domain linkifies', out.count('<a ') == 1, out)
check('bare domain gains https', 'href="https://smallscholars.com.au"' in out, out)
check('bare domain opens in a new tab',
      'target="_blank"' in out and 'rel="noopener noreferrer"' in out, out)

out = sanitize_reply('See https://x.example.com/page. Thanks')
check('trailing full stop stays out of the href',
      'href="https://x.example.com/page"' in out, out)
check('trailing full stop is still shown', '</a>. Thanks' in out, out)

out = sanitize_reply('Email us at hi@example.com')
check('email renders bold', '<strong>hi@example.com</strong>' in out, out)
check('email is not also linkified', '<a' not in out, out)

out = sanitize_reply('Call 555-123-4567 now')
check('phone renders bold', '<strong>555-123-4567</strong>' in out, out)

out = sanitize_reply('<a href="https://a.test/">visit b.test now</a>')
check('no linkifying inside an existing anchor', out.count('<a ') == 1, out)

out = sanitize_reply('<code>see example.com</code>')
check('no linkifying inside code', '<a' not in out, out)

out = sanitize_reply('Contact bob@x.com or see x.com/page')
check('an email does not swallow a later URL',
      '<strong>bob@x.com</strong>' in out and out.count('<a ') == 1, out)

out = sanitize_reply('Attach report.pdf and see e.g. the notes')
check('bare non-TLD tokens are left alone', '<a' not in out, out)

# ------------------------------------------------------------- plain replies
print('\nPlain replies are left alone')

check('plain text is returned byte-identical',
      sanitize_reply('Hello there!') == 'Hello there!',
      sanitize_reply('Hello there!'))
check('bare < and & are escaped',
      sanitize_reply('5 < 6 & 7 > 2') == '5 &lt; 6 &amp; 7 &gt; 2',
      sanitize_reply('5 < 6 & 7 > 2'))

# ------------------------------------------------------------- idempotence
print('\nIdempotence (double-processing is what caused the bug)')

for label, sample in [
    ('reported reply', REPORTED),
    ('bare URL', REPORTED_PLAIN),
    ('email', 'Email us at hi@example.com'),
    ('phone', 'Call 555-123-4567 now'),
    ('bold email', '<strong>hi@example.com</strong>'),
    ('plain text', 'Hello there!'),
    ('nested anchors', '<a href="https://a.test/">one <a href="https://b.test/">two</a></a>'),
]:
    once = sanitize_reply(sample)
    check(f'{label} is stable under a second pass', sanitize_reply(once) == once, once)

# ------------------------------------------------------------------- edges
print('\nEdge cases')

for label, value in [('None', None), ('empty', ''), ('whitespace', '   '), ('int', 7)]:
    try:
        out = sanitize_reply(value)
        check(f'{label} input returns a string without raising', isinstance(out, str), repr(out))
    except Exception as exc:
        check(f'{label} input returns a string without raising', False, repr(exc))

stats = {}
out = sanitize_reply('x' * (MAX_REPLY_CHARS + 5000), stats_sink=stats)
check('oversized input is truncated', stats.get('truncated') is True)
check('oversized input still returns', len(out) <= MAX_REPLY_CHARS, str(len(out)))

stats = {}
sanitize_reply('<script>x</script>', stats_sink=stats)
check('stats record the dropped tag', stats.get('tags_dropped') == 1, str(stats))
check('stats carry lengths, not text',
      'chars_in' in stats and 'chars_out' in stats, str(stats))

# --------------------------------------------------------------- plain text
print('\nreply_to_plain_text')

check('plain text strips the anchor but keeps the words',
      reply_to_plain_text(REPORTED) == 'You can also book online here: Book now',
      reply_to_plain_text(REPORTED))
check('plain text leaves a plain reply alone',
      reply_to_plain_text('Hello there!') == 'Hello there!')
check('plain text drops script contents',
      'alert' not in reply_to_plain_text('Hi<script>alert(1)</script>'))
check('plain text carries no markup', '<' not in reply_to_plain_text(REPORTED))

# ------------------------------------------------------------ route-level
print('\nPOST /api/chat/<embed_code>')

from app import (create_app, current_period_key, db, Chatbot,  # noqa: E402
                 Conversation, Plan, TokenUsage, User, UserSubscription)
from werkzeug.security import generate_password_hash  # noqa: E402
import services.chat_service as chat_service_module  # noqa: E402
from services.chat_service_openai import ChatServiceOpenAI  # noqa: E402

CANNED = REPORTED


def _fake_get_response(self, chatbot_id, user_message, conversation_id=None):
    return CANNED


chat_service_module.ChatService.get_response = _fake_get_response


def _no_network(self, *a, **kw):
    raise AssertionError('qa_phase6 must never reach OpenAI')


# Belt and braces: if an OpenAI client is ever constructed despite the empty
# key, this turns a silent live call into a loud failure.
ChatServiceOpenAI.get_response_with_usage = _no_network
ChatServiceOpenAI.get_response = _no_network

app = create_app()

with app.app_context():
    plan = Plan(name='P6 Plan', description='qa', monthly_price=0, yearly_price=0,
                chatbot_limit=9, file_size_limit_mb=20,
                allowed_models=json.dumps(['luna']), monthly_token_limit=1_000_000,
                web_search_enabled=False, is_active=True)
    capped = Plan(name='P6 Capped', description='qa', monthly_price=0, yearly_price=0,
                  chatbot_limit=9, file_size_limit_mb=20,
                  allowed_models=json.dumps(['luna']), monthly_token_limit=1,
                  web_search_enabled=False, is_active=True)
    db.session.add_all([plan, capped])
    db.session.commit()

    owner = User(username='p6owner', email='p6owner@example.com',
                 password_hash=generate_password_hash('pw'))
    broke = User(username='p6broke', email='p6broke@example.com',
                 password_hash=generate_password_hash('pw'))
    db.session.add_all([owner, broke])
    db.session.commit()
    db.session.add_all([
        UserSubscription(user_id=owner.id, plan_id=plan.id, status='active',
                         created_at=datetime.utcnow()),
        UserSubscription(user_id=broke.id, plan_id=capped.id, status='active',
                         created_at=datetime.utcnow()),
    ])

    bot = Chatbot(name='P6 Bot', url_name='p6-bot', description='qa',
                  embed_code=str(uuid.uuid4()), user_id=owner.id, model_alias='luna',
                  system_prompt='be helpful', is_trained=True)
    db.session.add(bot)
    db.session.commit()
    bot_code, bot_id = bot.embed_code, bot.id

client = app.test_client()
resp = client.post(f'/api/chat/{bot_code}', json={'message': 'how do I book?'})
check('chat route answers 200', resp.status_code == 200, str(resp.status_code))

if resp.status_code == 200:
    body = resp.get_json()
    check('route returns response_html', bool(body.get('response_html')), str(body)[:200])
    check('response_html has one clean anchor', body.get('response_html', '').count('<a ') == 1,
          body.get('response_html'))
    check('response_html does not leak the attribute',
          LEAKED not in body.get('response_html', ''))
    check('legacy response field carries no markup', '<' not in body.get('response', ''),
          body.get('response'))
    check('legacy response still carries the words',
          'Book now' in body.get('response', ''), body.get('response'))

    with app.app_context():
        stored = Conversation.query.filter_by(chatbot_id=bot_id).first()
        check('bot_response is stored RAW, byte for byte',
              stored is not None and stored.bot_response == CANNED,
              (stored.bot_response if stored else 'no row'))

# A reply that is entirely markup must not become an empty bubble.
CANNED = '<script>alert(1)</script>'
resp = client.post(f'/api/chat/{bot_code}', json={'message': 'again'})
if resp.status_code == 200:
    body = resp.get_json()
    check('an all-markup reply still yields non-empty html',
          bool(body.get('response_html', '').strip()), str(body)[:200])
    check('an all-markup reply does not ship the payload',
          'alert(' not in body.get('response_html', ''), body.get('response_html'))
CANNED = REPORTED

# The token-limit branch returns early; it must have the same shape.
with app.app_context():
    over = Chatbot(name='P6 Over', url_name='p6-over', description='qa',
                   embed_code=str(uuid.uuid4()), user_id=broke.id if False else None,
                   model_alias='luna', system_prompt='hi', is_trained=True)
    over.user_id = User.query.filter_by(username='p6broke').first().id
    db.session.add(over)
    db.session.commit()
    over_code = over.embed_code

with app.app_context():
    # The cap blocks at usage >= limit, so seed a period row: a fresh account
    # with a 1-token cap and no spend is still under it.
    db.session.add(TokenUsage(user_id=User.query.filter_by(username='p6broke').first().id,
                              chatbot_id=None, period_key=current_period_key(),
                              source='chat', prompt_tokens=50, completion_tokens=50,
                              total_tokens=100, request_count=1))
    db.session.commit()

resp = client.post(f'/api/chat/{over_code}', json={'message': 'hello'})
if resp.status_code == 200:
    body = resp.get_json()
    if body.get('limit_reached'):
        check('token-limit reply also carries response_html',
              'response_html' in body, str(body)[:200])
        check('token-limit reply text carries no markup',
              '<' not in body.get('response', ''), body.get('response'))
    else:
        check('token-limit branch was exercised', False, 'limit not reached; check plan cap')

# ------------------------------------------------------------ drift guards
print('\nDrift guards (there is no build step; this is the only one)')

CLIENT_ROOTS = ('static', 'templates')
offenders = []
for root in CLIENT_ROOTS:
    for dirpath, _dirnames, filenames in os.walk(root):
        if 'chatbot_env' in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(('.js', '.html')):
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = io.open(path, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                continue
            if 'convertLinksToHtml' in text:
                offenders.append(path)
check('the old client-side link regex is gone everywhere', not offenders, ', '.join(offenders))

BEGIN = '===== owlbee-safe-html v1 BEGIN'
END = '===== owlbee-safe-html v1 END ====='


def helper_block(path):
    text = io.open(path, encoding='utf-8').read()
    if BEGIN not in text or END not in text:
        return None
    body = text[text.index(BEGIN):text.index(END)]
    # Indentation differs: one copy sits inside the widget's IIFE.
    return '\n'.join(line.strip() for line in body.split('\n') if line.strip())


shared = helper_block('static/js/owlbee-safe-html.js')
widget = helper_block('static/js/chatbot-embed.js')
check('shared helper block is present', shared is not None)
check('widget carries a mirrored helper block', widget is not None)
check('the two helper copies have not drifted', shared is not None and shared == widget,
      'blocks differ' if shared != widget else '')

for path, needle in [
    ('static/js/chatbot-embed.js', 'data.response_html'),
    ('templates/chatbot_details.html', 'data.response_html'),
    ('templates/admin/chatbot_details.html', 'data.response_html'),
    ('templates/embed.html', 'data.response_html'),
]:
    text = io.open(path, encoding='utf-8').read()
    check(f'{path} reads response_html', needle in text)

# The dashboard's JSON tables need a whole JSON blob in one string, which the
# server's linkifier can split. renderBotMessage falls back to the whole-string
# pipeline for those replies; if that guard is removed, tables vanish silently.
dash = io.open('templates/chatbot_details.html', encoding='utf-8').read()
check('renderBotMessage still takes the plain-text twin',
      'function renderBotMessage(html, plainText)' in dash)
check('renderBotMessage keeps the JSON-table guard',
      'parseJsonTables(plainText) !== plainText' in dash)
check('the bot call site passes both fields',
      "renderBotMessage(data.response_html || data.response || '', data.response || '')" in dash)
check('the cosmetic pass is scoped to text nodes',
      'OwlbeeSafeHtml.walkTextNodes(frag' in dash)

for path in ('templates/base.html', 'templates/admin/base.html', 'templates/embed.html'):
    text = io.open(path, encoding='utf-8').read()
    check(f'{path} loads the shared helper', 'owlbee-safe-html.js' in text)

failed = [n for n, ok in results if not ok]
print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
for name in failed:
    print('  FAILED:', name)
sys.exit(1 if failed else 0)
