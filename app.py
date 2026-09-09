from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file, session, abort, Response, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import json
import logging
import mimetypes
import time
import uuid
from io import BytesIO
import secrets
import resend
import re
from datetime import datetime, timedelta
from services.document_processor import DocumentProcessor
from services.chatbot_trainer import ChatbotTrainer, artifact_version, get_trainer
from services.chat_service_openai import ChatServiceOpenAI
from services.analytics_service import AnalyticsService
from services.crypto import encrypt_secret, decrypt_secret, encryption_status
from services import model_catalog
from services import training_runner
from services.logging_setup import RunLogger, configure_logging, get_logger
from services.object_storage import (PRIVATE, PUBLIC, StorageError, StorageNotFound,
                                     artifact_key, avatar_key, describe_storage,
                                     document_key, get_storage, log_storage_status)
from services.reply_sanitizer import reply_to_plain_text, sanitize_reply
from services.training_errors import friendly_error

# Monthly token allowance applied to the auto-created Free plan. Paid plans get
# their allowance from the admin UI; see migrate_add_token_usage.py for the
# values backfilled onto the seeded plans.
FREE_PLAN_TOKEN_LIMIT = 100000

# Shown to a chat visitor when the bot's owner is over their monthly allowance.
# Deliberately says nothing about billing - the visitor is a stranger on the
# customer's website. Admin-overridable via the 'token_limit_message' setting.
DEFAULT_TOKEN_LIMIT_MESSAGE = (
    "I'm taking a short break right now and can't answer new questions. "
    "Please try again later or contact us directly."
)

# ----------------------------------------------------------------------
# Request logging
# ----------------------------------------------------------------------

_web_log = get_logger('owlbee.web')

# A request slower than this gets a line even when it succeeded. An upload that
# "hangs" in the browser is either absent from the log entirely (it never
# arrived) or present with a large ms - and those two need different fixes.
SLOW_REQUEST_MS = int(os.environ.get('SLOW_REQUEST_MS') or 3000)

# Static assets and the health probe are most of the request volume and none of
# the interesting failures.
QUIET_PATH_PREFIXES = ('/static/', '/favicon', '/health')


def request_logger(**fields):
    """Logger bound to the current request so all its lines share a request_id.

    That id is also returned to the browser as X-Request-Id, which is what turns
    "the upload spun forever" into a single grep.

    Tolerates being called outside a request context: the storage helpers it
    wraps are also reached from the training thread.
    """
    bound = {}
    try:
        request_id = getattr(g, 'request_id', None)
        if request_id:
            bound['request_id'] = request_id
    except Exception:
        pass
    try:
        if current_user.is_authenticated:
            bound['user_id'] = current_user.id
    except Exception:
        pass
    bound.update({k: v for k, v in fields.items() if v is not None})
    return RunLogger(_web_log, **bound)


# Optional Stripe dependency (guarded)
try:
    import stripe  # type: ignore
except Exception:
    stripe = None

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, skip loading .env file
    pass

db = SQLAlchemy()
login_manager = LoginManager()

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Profile fields
    full_name = db.Column(db.String(100), nullable=True)
    business_name = db.Column(db.String(100), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    chatbots = db.relationship('Chatbot', backref='owner', lazy=True, cascade='all, delete-orphan')

class Chatbot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url_name = db.Column(db.String(100), nullable=True)  # URL-friendly name (no spaces, special chars)
    description = db.Column(db.Text)
    system_prompt = db.Column(db.Text, default="You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.")
    model_alias = db.Column(db.String(20), nullable=True)  # 'sol'|'terra'|'luna'; NULL = follow the global default
    embed_code = db.Column(db.String(36), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_trained = db.Column(db.Boolean, default=False)
    avatar_filename = db.Column(db.String(255), nullable=True)  # Custom avatar image
    greeting_message = db.Column(db.String(500), nullable=True)  # Custom greeting message
    homepage_url = db.Column(db.String(500), nullable=True)  # Homepage URL
    contact_us_url = db.Column(db.String(500), nullable=True)  # Contact US URL
    # Set only by a training run that actually succeeded. is_trained alone cannot
    # answer "trained when, and by which run" - which is what turns a support
    # report into a log lookup, and what makes the missing-artifact case (a deploy
    # wiped training_data/) detectable instead of a surprise at chat time.
    last_trained_at = db.Column(db.DateTime, nullable=True)
    last_training_run_id = db.Column(db.String(36), nullable=True)
    documents = db.relationship('Document', backref='chatbot', lazy=True, cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='chatbot', lazy=True, cascade='all, delete-orphan')

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    # Legacy: an OS path from before object storage. Values are a mix of
    # absolute Windows paths, absolute Linux paths and relative ones, so a
    # storage key is not distinguishable from them by inspection - which is why
    # storage_key is a separate column rather than an overload of this one.
    # No longer written; kept because it is the only recovery information for
    # any row the migration to Bunny missed.
    file_path = db.Column(db.String(500), nullable=False)
    storage_key = db.Column(db.String(500), nullable=True)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    # Raw model output, deliberately unsanitized: this is the audit record of
    # what the model actually produced, and sanitizing on write would be lossy
    # and irreversible. NEVER render it as HTML. The two transcript previews
    # are Jinja-autoescaped; anything new must go through
    # services.reply_sanitizer.sanitize_reply first.
    bot_response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    response_status = db.Column(db.String(20), default='active')  # 'active', 'resolved', 'pending'
    # Per-request token ledger. Nullable because the local (non-OpenAI) fallback
    # path reports no usage. Lets the TokenUsage rollup be rebuilt with a GROUP BY.
    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)
    model_alias = db.Column(db.String(20), nullable=True)

class ChatbotUsage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    website_url = db.Column(db.String(500), nullable=False)
    website_domain = db.Column(db.String(255), nullable=False)
    website_title = db.Column(db.String(255), nullable=True)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    usage_count = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    chatbot = db.relationship('Chatbot', backref='usage_tracking')

class TokenUsage(db.Model):
    """Rolled-up token spend per (user, chatbot, month, source).

    Rolled up rather than one row per request because the cap is read on every
    single chat message - a SUM() over a per-request table would degrade exactly
    as the product succeeds. The per-request detail lives on Conversation.

    period_key is a calendar month in UTC ('YYYY-MM'), so a new month simply
    finds no row and starts at zero. That is the whole reset mechanism: there is
    no scheduled job that could fail and leave paying customers blocked.
    """
    __tablename__ = 'token_usage'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=True)
    period_key = db.Column(db.String(7), nullable=False)  # 'YYYY-MM', UTC
    source = db.Column(db.String(20), nullable=False, default='chat')  # chat|training|analytics|embedding
    prompt_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    completion_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    total_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    request_count = db.Column(db.Integer, nullable=False, default=0)
    blocked_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'chatbot_id', 'period_key', 'source',
                            name='uq_token_usage_period'),
        db.Index('ix_token_usage_user_period', 'user_id', 'period_key'),
    )

class TrainingRun(db.Model):
    """One attempt to (re)train one chatbot.

    Training runs in a daemon thread, so this row - not the thread - is the
    source of truth. A Render restart kills the thread mid-flight and the only
    way the UI can tell "still working" from "died" is a heartbeat it outlives;
    that is what heartbeat_at and host are for. It also means a user can close
    the tab, come back, and still see the run.
    """
    __tablename__ = 'training_run'
    id = db.Column(db.Integer, primary_key=True)
    # uuid4 hex. Doubles as the log correlation id, so a failure a user reports
    # maps to a log grep in one hop.
    run_id = db.Column(db.String(36), unique=True, nullable=False)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # queued|running|succeeded|failed|orphaned|cancelled. 'orphaned' is kept
    # distinct from 'failed' so "the server restarted" stays separable from
    # "OpenAI rejected it" in logs and in support conversations.
    status = db.Column(db.String(20), nullable=False, default='queued')
    phase = db.Column(db.String(32), nullable=False, default='queued')
    progress = db.Column(db.Integer, nullable=False, default=0)   # 0..100
    message = db.Column(db.String(255), nullable=True)            # current step, human-readable

    error_code = db.Column(db.String(40), nullable=True)          # see services/training_errors.py
    error_message = db.Column(db.Text, nullable=True)             # raw detail, shown under <details>

    model_alias = db.Column(db.String(20), nullable=True)
    doc_count = db.Column(db.Integer, nullable=True)
    char_count = db.Column(db.Integer, nullable=True)
    chunk_count = db.Column(db.Integer, nullable=True)

    prompt_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    completion_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    total_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    embedding_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    api_attempts = db.Column(db.Integer, nullable=False, default=0)  # incl. retries

    host = db.Column(db.String(64), nullable=True)                # "hostname:pid"; the reaper keys on this
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_training_run_chatbot', 'chatbot_id', 'created_at'),
        db.Index('ix_training_run_status', 'status', 'heartbeat_at'),
    )


# A run in one of these states is over; the browser stops polling and the reaper
# leaves it alone.
TRAINING_TERMINAL_STATUSES = ('succeeded', 'failed', 'orphaned', 'cancelled')


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    monthly_price = db.Column(db.Float, nullable=False, default=0.0)
    yearly_price = db.Column(db.Float, nullable=False, default=0.0)
    stripe_monthly_price_id = db.Column(db.String(255))
    stripe_yearly_price_id = db.Column(db.String(255))
    chatbot_limit = db.Column(db.Integer, nullable=False, default=1)
    file_size_limit_mb = db.Column(db.Integer, nullable=False, default=10)  # File size limit in MB
    allowed_models = db.Column(db.Text)  # JSON array of model aliases, e.g. '["luna","terra"]'
    monthly_token_limit = db.Column(db.BigInteger, nullable=True)  # NULL or <= 0 means unlimited
    web_search_enabled = db.Column(db.Boolean, default=False)  # May bots on this plan use the web-search model
    features = db.Column(db.Text)  # JSON string of features
    is_active = db.Column(db.Boolean, default=True)
    show_contact_sales = db.Column(db.Boolean, default=False)  # Show Contact Sales button instead of Stripe checkout
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='active')
    current_period_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='password_reset_tokens')

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_title = db.Column(db.String(255), nullable=False, default='ChatBot Platform')
    logo_filename = db.Column(db.String(255), nullable=True)  # Keep for backward compatibility
    logo_base64 = db.Column(db.Text, nullable=True)  # Store base64 encoded image
    meta_tags = db.Column(db.Text, nullable=True)  # Comma-separated meta tags
    hero_title = db.Column(db.String(255), nullable=False, default='Build your own AI chatbot')
    hero_subtitle = db.Column(db.Text, nullable=True)
    hero_icon_filename = db.Column(db.String(255), nullable=True)  # Keep for backward compatibility
    hero_icon_base64 = db.Column(db.Text, nullable=True)  # Store base64 encoded hero icon
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, default=0, nullable=False)  # For ordering FAQ items
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class HomepageSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    section_type = db.Column(db.String(50), nullable=False)  # 'how_it_works', 'features', 'stats', 'cta'
    title = db.Column(db.String(255), nullable=True)
    subtitle = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)  # JSON content for complex sections
    order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_user_plan(user):
    """Get the user's current plan based on active subscription, else Free."""
    # Admin users get unlimited access
    if user.is_admin:
        # Get admin plan with unlimited access
        admin_plan = Plan.query.filter_by(name='Admin').first()
        if not admin_plan:
            try:
                admin_plan = Plan(
                    name='Admin',
                    description='Admin plan with unlimited access',
                    monthly_price=0.0,
                    yearly_price=0.0,
                    chatbot_limit=999999,  # Effectively unlimited
                    file_size_limit_mb=999999,  # Effectively unlimited
                    allowed_models=json.dumps(model_catalog.all_aliases()),
                    monthly_token_limit=None,  # Unlimited
                    web_search_enabled=True,
                    features=json.dumps(['Unlimited chatbots', 'Unlimited file uploads', 'Admin access']),
                    is_active=True
                )
                db.session.add(admin_plan)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                # If creation fails, try to get existing admin plan
                admin_plan = Plan.query.filter_by(name='Admin').first()
                if not admin_plan:
                    # If still no plan, create a fallback plan object
                    admin_plan = Plan(
                        name='Admin',
                        description='Admin plan with unlimited access',
                        monthly_price=0.0,
                        yearly_price=0.0,
                        chatbot_limit=999999,
                        file_size_limit_mb=999999,
                        allowed_models=json.dumps(model_catalog.all_aliases()),
                        monthly_token_limit=None,  # Unlimited
                        web_search_enabled=True,
                        features=json.dumps(['Unlimited chatbots', 'Unlimited file uploads', 'Admin access']),
                        is_active=True
                    )
        return admin_plan
    
    try:
        sub = UserSubscription.query.filter_by(user_id=user.id, status='active').order_by(UserSubscription.created_at.desc()).first()
        if sub:
            plan = Plan.query.get(sub.plan_id)
            if plan and plan.is_active:
                return plan
    except Exception:
        pass

    free_plan = Plan.query.filter_by(name='Free', is_active=True).first()
    if not free_plan:
        free_plan = Plan(
            name='Free',
            description='Free plan for all users',
            monthly_price=0.0,
            yearly_price=0.0,
            chatbot_limit=3,
            allowed_models=json.dumps([model_catalog.CHEAPEST_ALIAS]),
            monthly_token_limit=FREE_PLAN_TOKEN_LIMIT,
            web_search_enabled=False,
            features=json.dumps(['Up to 3 chatbots', 'Basic support']),
            is_active=True
        )
        db.session.add(free_plan)
        db.session.commit()
    return free_plan


def get_allowed_models(plan):
    """Model aliases this plan may use.

    Fails closed to the cheapest tier: guessing "all" would silently hand a $0
    plan the most expensive model and we would eat the bill, while guessing
    "cheapest" only costs a support ticket.
    """
    if plan is None:
        return [model_catalog.CHEAPEST_ALIAS]
    if getattr(plan, 'name', None) == 'Admin':
        return model_catalog.all_aliases()
    try:
        raw = json.loads(plan.allowed_models) if plan.allowed_models else []
    except Exception:
        raw = []
    return model_catalog.filter_allowed(raw) or [model_catalog.CHEAPEST_ALIAS]


def plan_allows_web_search(plan):
    """Web search runs on a fixed, pricier model, so it is sold per plan."""
    if plan is None:
        return False
    if getattr(plan, 'name', None) == 'Admin':
        return True
    return bool(getattr(plan, 'web_search_enabled', False))


def resolve_model_for_chatbot(chatbot):
    """The alias this bot should actually run on right now. Never raises.

    Per-bot value wins; the global 'openai_model' setting is the fallback for
    bots that have never picked one. If a plan change left the bot on a tier its
    owner no longer pays for, quietly cap it at the best tier the plan does
    allow - a billing change should not break a live widget on a customer site.
    """
    try:
        alias = model_catalog.normalize_alias(
            getattr(chatbot, 'model_alias', None)
            or get_setting_value('openai_model', model_catalog.DEFAULT_ALIAS))
        owner = User.query.get(chatbot.user_id)
        if not owner:
            return alias
        allowed = get_allowed_models(get_user_plan(owner))
        if alias not in allowed:
            downgraded = model_catalog.best_allowed(allowed)
            print(f"[INFO] chatbot {chatbot.id}: tier '{alias}' not in owner's plan, using '{downgraded}'")
            return downgraded
        return alias
    except Exception as e:
        print(f"[WARNING] model resolution failed for chatbot {getattr(chatbot, 'id', None)}: {e}")
        return model_catalog.DEFAULT_ALIAS


def audit_missing_training_data():
    """Log every chatbot marked trained whose knowledge base is missing.

    One listing of the training prefix rather than a lookup per chatbot: at cold
    start those would be N network round trips, and Render's port-bind deadline
    is real.
    """
    missing = []
    try:
        present = set()
        for entry in get_storage().list(PRIVATE, 'training/'):
            name = entry['name']
            if name.startswith('chatbot_') and name.endswith('.json'):
                try:
                    present.add(int(name[len('chatbot_'):-len('.json')]))
                except ValueError:
                    continue
        for chatbot in Chatbot.query.filter_by(is_trained=True).all():
            if chatbot.id not in present:
                missing.append(chatbot)
    except Exception as error:
        print(f"[STORAGE] Could not audit training data: {error}")
        return []

    for chatbot in missing:
        logging.getLogger('owlbee.training').warning(
            'training.artifact_missing',
            extra={'owlbee': {'event': 'training.artifact_missing',
                              'chatbot_id': chatbot.id,
                              'chatbot_name': chatbot.name,
                              'last_trained_at': str(chatbot.last_trained_at)}})
    if missing:
        print(f"[STORAGE] WARNING: {len(missing)} chatbot(s) are marked trained but have "
              f"no knowledge base in storage. They need retraining: "
              f"{', '.join(str(c.id) for c in missing[:20])}")
    return missing


def check_text_size(text, user):
    """(data, error_message) for generated text, against the uploader's plan limit.

    The Google Doc / Sheet / website importers wrote unbounded text to a local
    disk before. Storage is billed per GB and the scraper pulls up to 50 pages,
    so they get the same limit the file-upload path already enforces.
    """
    data = text.encode('utf-8')
    try:
        limit_mb = get_user_plan(user).file_size_limit_mb or 10
    except Exception:
        limit_mb = 10
    if len(data) > limit_mb * 1024 * 1024:
        return None, (f'The imported content is {len(data) / (1024 * 1024):.1f}MB, which '
                      f'exceeds your plan limit of {limit_mb}MB. Import a smaller '
                      f'document or upgrade your plan.')
    return data, None


def store_document_bytes(chatbot_id, filename, data, content_type=None, logger=None):
    """Upload a document and return (unique_filename, storage_key).

    Raises StorageError. Callers upload BEFORE committing the row: the reverse
    leaves rows pointing at objects that do not exist, whereas this ordering can
    only leave an object with no row - which costs a little storage and is swept
    by migrate_to_bunny.py --audit.

    `logger` is threaded through to the storage call so its retry and failure
    lines carry the request id and chatbot id rather than standing alone.
    """
    unique_filename = f"{uuid.uuid4()}_{secure_filename(filename)}"
    key = document_key(chatbot_id, unique_filename)
    get_storage().put(PRIVATE, key, data, content_type=content_type, logger=logger)
    return unique_filename, key


def app_upload_folder():
    """Legacy local upload root, for rows that predate object storage."""
    from flask import current_app
    try:
        return current_app.config.get('UPLOAD_FOLDER', 'uploads')
    except RuntimeError:
        return 'uploads'


def load_document_bytes(document):
    """The document's bytes, or None if it is genuinely gone.

    Two branches: rows written since the move to object storage carry a
    storage_key; older rows still carry a local file_path.
    """
    if getattr(document, 'storage_key', None):
        try:
            return get_storage().get(PRIVATE, document.storage_key)
        except StorageNotFound:
            return None
    path = resolve_document_path(document, app_upload_folder())
    if not path:
        return None
    try:
        with open(path, 'rb') as handle:
            return handle.read()
    except OSError:
        return None


def delete_document_object(document):
    """Best-effort delete of whatever this row points at. Never raises.

    Failing a chatbot deletion because a DELETE returned 500 would strand the
    user, so failures are logged rather than raised - with the key, so the
    orphan is greppable and the audit sweep can find it.
    """
    if getattr(document, 'storage_key', None):
        try:
            get_storage().delete(PRIVATE, document.storage_key)
        except StorageError as error:
            logging.getLogger('owlbee.storage').warning(
                'storage.delete_failed',
                extra={'owlbee': {'event': 'storage.delete_failed',
                                  'key': document.storage_key, 'error': str(error)}})
        return
    try:
        if document.file_path and os.path.exists(document.file_path):
            os.remove(document.file_path)
    except Exception as error:
        print(f"Error deleting file {document.file_path}: {error}")


def resolve_document_path(document, upload_folder):
    """Locate a LEGACY document on local disk, or None.

    Only for rows with no storage_key - documents written before the move to
    object storage. Stored paths are unreliable across environments: rows
    written on Windows carry backslashes, and a deploy changes the upload root.
    """
    candidates = [document.file_path,
                  os.path.join(upload_folder, document.filename),
                  os.path.join(upload_folder,
                               os.path.basename((document.file_path or '').replace('\\', '/')))]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def training_data_for_display(training_data, include_vectors=False):
    """Shallow copy with the embedding vectors replaced by a summary.

    A v3 artifact carries megabytes of base64 float32. The "View Training Data"
    modal renders JSON as text, so shipping the vectors would hang the browser
    for content no human reads.
    """
    if not isinstance(training_data, dict):
        return training_data
    index = training_data.get('index')
    if not isinstance(index, dict) or include_vectors or 'vectors_b64' not in index:
        return training_data
    shown = dict(training_data)
    shown_index = dict(index)
    shown_index['vectors_b64'] = (f"<omitted: {index.get('count', 0)} vectors x "
                                  f"{index.get('dimensions', 0)} dims>")
    shown['index'] = shown_index
    return shown


def purge_training_runs(chatbot_id):
    """Drop a chatbot's training runs. Call before deleting the chatbot.

    They hold an FK to chatbot, so Postgres refuses the delete otherwise.
    Cancelling first makes any in-flight worker abort at its next checkpoint
    rather than re-inserting rows behind the delete.
    """
    try:
        TrainingRun.query.filter_by(chatbot_id=chatbot_id).update(
            {TrainingRun.status: 'cancelled'}, synchronize_session=False)
        TrainingRun.query.filter_by(chatbot_id=chatbot_id).delete(synchronize_session=False)
    except Exception as error:
        print(f"Error deleting training runs for chatbot {chatbot_id}: {error}")


def detach_token_usage(chatbot_id):
    """Unhook a chatbot's metered spend. Call before deleting the chatbot.

    token_usage holds an FK to chatbot, so Postgres refuses the delete
    otherwise - and SQLite does not, which is why this only shows up against
    the real database.

    The rows are detached rather than deleted: chatbot_id is nullable, and
    Postgres treats NULLs as distinct in the unique constraint, so several
    detached rows can coexist for the same user and month. Deleting them
    instead would let a customer zero their bill for the month by deleting the
    chatbot that spent it.
    """
    try:
        TokenUsage.query.filter_by(chatbot_id=chatbot_id).update(
            {TokenUsage.chatbot_id: None}, synchronize_session=False)
    except Exception as error:
        print(f"Error detaching token usage for chatbot {chatbot_id}: {error}")


def current_period_key():
    """Calendar month in UTC.

    Calendar month rather than the Stripe billing period because
    UserSubscription.current_period_end is never maintained - the webhook
    handler is a stub - so a period-derived window would be wrong for every
    user past their first month.
    """
    return datetime.utcnow().strftime('%Y-%m')


def record_token_usage(user_id, chatbot_id, usage, source='chat', blocked=False):
    """Best-effort metering. Must never raise into the chat path."""
    if not user_id:
        return
    usage = usage or {}
    pt = int(usage.get('prompt_tokens') or 0)
    ct = int(usage.get('completion_tokens') or 0)
    tt = int(usage.get('total_tokens') or 0)
    period = current_period_key()
    try:
        # UPDATE first, with the increment pushed into SQL, so two concurrent
        # writers cannot lose an update the way a read-modify-write would.
        rows = db.session.query(TokenUsage).filter_by(
            user_id=user_id, chatbot_id=chatbot_id,
            period_key=period, source=source
        ).update({
            TokenUsage.prompt_tokens: TokenUsage.prompt_tokens + pt,
            TokenUsage.completion_tokens: TokenUsage.completion_tokens + ct,
            TokenUsage.total_tokens: TokenUsage.total_tokens + tt,
            TokenUsage.request_count: TokenUsage.request_count + (0 if blocked else 1),
            TokenUsage.blocked_count: TokenUsage.blocked_count + (1 if blocked else 0),
            TokenUsage.updated_at: datetime.utcnow(),
        }, synchronize_session=False)
        if rows == 0:
            db.session.add(TokenUsage(
                user_id=user_id, chatbot_id=chatbot_id,
                period_key=period, source=source,
                prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
                request_count=0 if blocked else 1,
                blocked_count=1 if blocked else 0))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARNING] token usage not recorded (user={user_id}): {e}")


def get_period_usage(user_id, period_key=None):
    """Total tokens this user has spent in the period, across all sources."""
    period = period_key or current_period_key()
    try:
        total = db.session.query(
            db.func.coalesce(db.func.sum(TokenUsage.total_tokens), 0)
        ).filter(
            TokenUsage.user_id == user_id,
            TokenUsage.period_key == period,
        ).scalar()
        return int(total or 0)
    except Exception as e:
        print(f"[WARNING] could not read token usage for user {user_id}: {e}")
        return 0


def get_usage_summary(user, period_key=None):
    """Everything the dashboard and admin views need about one user's spend.

    Shaped like AnalyticsService: compute here, return a flat dict, hand it to
    the template as a single kwarg.
    """
    period = period_key or current_period_key()
    plan = get_user_plan(user)
    limit = get_token_allowance(plan)
    used = get_period_usage(user.id, period)

    by_source = {}
    blocked = 0
    try:
        rows = TokenUsage.query.filter_by(user_id=user.id, period_key=period).all()
        for row in rows:
            by_source[row.source] = by_source.get(row.source, 0) + int(row.total_tokens or 0)
            blocked += int(row.blocked_count or 0)
    except Exception as e:
        print(f"[WARNING] could not summarize token usage for user {user.id}: {e}")

    return {
        'period_key': period,
        'plan_name': getattr(plan, 'name', 'Unknown'),
        'limit': limit,
        'used': used,
        'remaining': None if limit is None else max(0, limit - used),
        'percent': None if limit is None else min(100, round(used * 100.0 / limit, 1)) if limit else 0,
        'over_limit': limit is not None and used >= limit,
        'by_source': by_source,
        'blocked_count': blocked,
    }


def get_token_allowance(plan):
    """Monthly token cap for a plan, or None when uncapped."""
    limit = getattr(plan, 'monthly_token_limit', None)
    if not limit or limit <= 0:
        return None
    return int(limit)


def check_token_allowance_for_user(user):
    """(allowed, message) for a known user. Fails OPEN on any error."""
    try:
        if not user:
            return True, None
        limit = get_token_allowance(get_user_plan(user))
        if limit is None:
            return True, None
        if get_period_usage(user.id) < limit:
            return True, None
        return False, get_setting_value('token_limit_message', DEFAULT_TOKEN_LIMIT_MESSAGE)
    except Exception as e:
        print(f"[WARNING] token allowance check failed, allowing request: {e}")
        return True, None


def check_token_allowance(chatbot):
    """(allowed, friendly_message) for an incoming chat request.

    Unlike every other quota check in this file, the plan is resolved from the
    bot's OWNER rather than current_user - chat visitors are anonymous, so
    current_user.user_plan is None for them.

    Fails OPEN: a bug in metering must not take down every embedded widget on
    our customers' websites.
    """
    try:
        owner = User.query.get(chatbot.user_id)
        if not owner:
            return True, None
        allowed, message = check_token_allowance_for_user(owner)
        if not allowed:
            record_token_usage(owner.id, chatbot.id, None, source='chat', blocked=True)
        return allowed, message
    except Exception as e:
        print(f"[WARNING] token allowance check failed, allowing request: {e}")
        return True, None


def get_site_settings():
    """Get the active site settings from the database."""
    site_settings = SiteSettings.query.filter_by(is_active=True).first()
    if not site_settings:
        # Create default site settings if none exist
        site_settings = SiteSettings(
            site_title='ChatBot Platform',
            meta_tags='chatbot, AI, customer service, automation',
            hero_title='Build your own AI chatbot',
            hero_subtitle='Create intelligent chatbots for your business in minutes'
        )
        db.session.add(site_settings)
        db.session.commit()
    return site_settings

def send_email(to_email, subject, body, is_html=False):
    """Send an email using Resend API."""
    try:
        # Set Resend API key
        resend.api_key = os.getenv('RESEND_API_KEY')
        if not resend.api_key:
            raise Exception("RESEND_API_KEY not configured")
        
        # Get sender information from environment variables
        from_email = os.getenv('RESEND_FROM_EMAIL')
        from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
        
        if not from_email:
            raise Exception("RESEND_FROM_EMAIL not configured")
        
        # Prepare email data
        email_data = {
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "subject": subject
        }
        
        # Add content based on type
        if is_html:
            email_data["html"] = body
        else:
            email_data["text"] = body
        
        print(f"DEBUG: Sending email with data: {email_data}")  # Debug log
        
        # Send email using Resend
        response = resend.Emails.send(email_data)
        
        print(f"DEBUG: Resend response: {response}")  # Debug log
        
        if response and (hasattr(response, 'id') or (isinstance(response, dict) and 'id' in response)):
            return True
        else:
            raise Exception(f"Invalid response from Resend: {response}")
            
    except Exception as e:
        print(f"DEBUG: Email error: {str(e)}")  # Debug log
        raise Exception(f"Failed to send email: {str(e)}")

def generate_password_reset_token(user):
    """Generate a password reset token for a user"""
    # Create a secure random token
    token = secrets.token_urlsafe(32)
    
    # Set expiration time (1 hour from now)
    expires_at = datetime.utcnow() + timedelta(hours=1)
    
    # Create the token record
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    
    db.session.add(reset_token)
    db.session.commit()
    
    return token

def send_password_reset_email(user, token):
    """Send password reset email to user"""
    # Create reset URL
    reset_url = f"{request.url_root}reset-password/{token}"
    
    # Get sender name from environment
    from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
    
    # Create email content
    subject = "Password Reset Request"
    body = f"""
Dear {user.username},

You have requested to reset your password for your Chatbot Platform account.

To reset your password, please click the link below:
{reset_url}

This link will expire in 1 hour for security reasons.

If you did not request this password reset, please ignore this email and your password will remain unchanged.

Best regards,
{from_name}
    """
    
    # Send email using Resend
    send_email(user.email, subject, body)

# Admin authentication
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            # For AJAX requests, return JSON error instead of redirect
            if (request.headers.get('Content-Type') == 'application/json' or 
                request.is_json or 
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def get_setting_value(key, default=None):
    """Read a plain (non-secret) setting from the database.

    Module-level twin of the get_setting() Jinja global defined inside
    create_app() - that one is only reachable from templates, so the services
    layer and helpers below need this one.
    """
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else default


def set_setting(key, value):
    """Set a setting value in the database"""
    setting = Settings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.utcnow()
    else:
        setting = Settings(key=key, value=value)
        db.session.add(setting)
    db.session.commit()
    return setting

def get_secret_setting(key, default=''):
    """Read a setting that is stored encrypted (see services/crypto.py).

    Deliberately separate from get_setting(), which is a Jinja global exposed to
    every template - decrypting in there would let any template render a live
    secret. Legacy plaintext values are passed through unchanged.
    """
    setting = Settings.query.filter_by(key=key).first()
    if not setting or not setting.value:
        return default
    return decrypt_secret(setting.value)

def set_secret_setting(key, value):
    """Write a setting encrypted at rest. Raises if encryption is unavailable,
    so a secret is never silently stored as plaintext."""
    return set_setting(key, encrypt_secret(value))

def update_secret_setting_from_form(key, submitted_value, clear_requested):
    """Apply a write-only secret field from an admin form.

    The field is never rendered back to the browser, so an empty submission
    means "keep the stored value"; wiping it requires the explicit clear checkbox.
    """
    if submitted_value:
        set_secret_setting(key, submitted_value)
    elif clear_requested:
        set_secret_setting(key, '')

def encode_image_to_base64(file):
    """Convert uploaded file to base64 data URL"""
    import base64
    import mimetypes
    
    if not file or not file.filename:
        return None
    
    # Get file extension and MIME type
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    mime_type = mimetypes.guess_type(file.filename)[0] or f'image/{file_ext}'
    
    # Read file content and encode
    file_content = file.read()
    file.seek(0)  # Reset file pointer for potential future use
    
    base64_content = base64.b64encode(file_content).decode('utf-8')
    return f"data:{mime_type};base64,{base64_content}"

def get_logo_url(site_settings):
    """Get logo URL - either base64 data URL or file URL"""
    if site_settings.logo_base64:
        return site_settings.logo_base64
    elif site_settings.logo_filename:
        return url_for('static', filename='uploads/' + site_settings.logo_filename)
    return None

def get_hero_icon_url(site_settings):
    """Get hero icon URL - either base64 data URL or file URL"""
    if site_settings.hero_icon_base64:
        return site_settings.hero_icon_base64
    elif site_settings.hero_icon_filename:
        return url_for('static', filename='uploads/' + site_settings.hero_icon_filename)
    return None

# Utility functions
def generate_url_name(name):
    """Generate a URL-friendly name from a chatbot name"""
    # Convert to lowercase and replace spaces with hyphens
    url_name = re.sub(r'[^a-zA-Z0-9\-_]', '', name.lower().replace(' ', '-'))
    # Remove multiple consecutive hyphens
    url_name = re.sub(r'-+', '-', url_name)
    # Remove leading/trailing hyphens
    url_name = url_name.strip('-')
    return url_name

def get_chatbot_url(chatbot):
    """Get the correct URL for a chatbot (new format: /username/chatbotname)"""
    if chatbot.url_name and chatbot.owner:
        return url_for('chatbot_details_by_name', username=chatbot.owner.username, chatbot_name=chatbot.url_name)
    else:
        # Fallback to old format if url_name is missing
        return url_for('chatbot_details', chatbot_id=chatbot.id)

def is_valid_chatbot_name(name):
    """Validate chatbot name for URL compatibility"""
    if not name or len(name.strip()) == 0:
        return False, "Chatbot name cannot be empty"
    
    if len(name) > 100:
        return False, "Chatbot name must be 100 characters or less"
    
    # Check for invalid characters
    if re.search(r'[<>:"/\\|?*]', name):
        return False, "Chatbot name cannot contain special characters: < > : \" / \\ | ? *"
    
    # Check for consecutive spaces
    if '  ' in name:
        return False, "Chatbot name cannot contain consecutive spaces"
    
    return True, "Valid"

def track_chatbot_usage(chatbot_id, website_url):
    """Track where a chatbot is being used"""
    try:
        from urllib.parse import urlparse
        
        # Parse the URL to get domain
        parsed_url = urlparse(website_url)
        domain = parsed_url.netloc
        
        # Skip tracking for localhost and our own domain
        if domain in ['localhost', '127.0.0.1', '0.0.0.0'] or domain.endswith('.local'):
            return
        
        # Check if usage already exists
        existing_usage = ChatbotUsage.query.filter_by(
            chatbot_id=chatbot_id, 
            website_domain=domain
        ).first()
        
        if existing_usage:
            # Update existing usage
            existing_usage.last_seen = datetime.utcnow()
            existing_usage.usage_count += 1
            existing_usage.is_active = True
        else:
            # Create new usage record
            usage = ChatbotUsage(
                chatbot_id=chatbot_id,
                website_url=website_url,
                website_domain=domain,
                website_title=None,  # Could be populated later with web scraping
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                usage_count=1,
                is_active=True
            )
            db.session.add(usage)
        
        db.session.commit()
    except Exception as e:
        print(f"Error tracking chatbot usage: {e}")
        # Don't fail the main request if tracking fails

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
    
    # Add custom Jinja2 filter for JSON parsing
    @app.template_filter('from_json')
    def from_json_filter(json_string):
        try:
            return json.loads(json_string)
        except:
            return []
    
    # Helper function to get avatar upload directory
    AVATAR_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    PREDEFINED_AVATARS = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']

    def store_avatar(avatar_file, logger=None):
        """Upload an avatar to the public zone. Returns its filename.

        Raises StorageError on an upload failure, so the caller can tell the
        user rather than saving a chatbot that points at a missing image.
        """
        log = logger or request_logger()
        filename = secure_filename(avatar_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        name_part, ext = os.path.splitext(filename)
        avatar_filename = f"avatar_{name_part}_{timestamp}{ext}"
        payload = avatar_file.read()
        started = time.monotonic()
        log.event('avatar.storing', bytes=len(payload), ext=ext.lstrip('.').lower())
        get_storage().put(PUBLIC, avatar_key(avatar_filename), payload,
                          content_type=avatar_file.mimetype, logger=log)
        log.event('avatar.stored', avatar=avatar_filename, bytes=len(payload),
                  ms=int((time.monotonic() - started) * 1000))
        return avatar_filename

    def delete_avatar(avatar_filename):
        """Best-effort removal of a custom avatar. Never raises.

        Predefined avatars are committed to the repo and must never be deleted.
        """
        if not avatar_filename or avatar_filename in PREDEFINED_AVATARS:
            return
        try:
            get_storage().delete(PUBLIC, avatar_key(avatar_filename))
        except Exception as error:
            # Leaves an orphaned object, which costs storage and nothing else -
            # so it stays non-fatal, but it no longer goes unrecorded.
            request_logger().warning('avatar.delete_failed', avatar=avatar_filename,
                                     error=f'{type(error).__name__}: {error}')
            print(f"Error deleting avatar {avatar_filename}: {error}")
    
    @app.template_global()
    def get_avatar_embed_url(avatar_filename):
        """Absolute avatar URL, for a snippet that runs on someone else's domain.

        Deliberately separate from get_avatar_url(): that one is interpolated in
        the embed template as '{{ domain }}{{ get_avatar_url(...) }}', where
        ${domain} is JS. If it ever returned an absolute URL, every new snippet
        would ship 'https://owlbee.comhttps://cdn...' - silently, onto customer
        sites. So get_avatar_url() stays relative and this is the absolute one.
        """
        if not avatar_filename:
            return ''
        allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
        if avatar_filename in allowed_predefined:
            return url_for('static', filename='avatars/' + avatar_filename, _external=True)
        cdn_url = get_storage().public_url(PUBLIC, avatar_key(avatar_filename))
        if cdn_url:
            return cdn_url
        return url_for('uploaded_file', filename=avatar_filename, _external=True)

    # Add custom Jinja2 function for avatar URL
    @app.template_global()
    def get_avatar_url(avatar_filename):
        if not avatar_filename:
            return None
        
        # Check if it's a predefined avatar
        allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
        if avatar_filename in allowed_predefined:
            return url_for('static', filename='avatars/' + avatar_filename)
        else:
            # Custom uploaded avatars are served from /uploads/<filename> route
            return url_for('uploaded_file', filename=avatar_filename)
    
    # Add custom Jinja2 function for getting settings
    @app.template_global()
    def get_setting(key, default=None):
        """Get a setting value from the database"""
        return get_setting_value(key, default)
    
    @app.template_global()
    def get_logo_url(site_settings):
        """Get logo URL - either base64 data URL or file URL"""
        if site_settings and site_settings.logo_base64:
            return site_settings.logo_base64
        elif site_settings and site_settings.logo_filename:
            return url_for('static', filename='uploads/' + site_settings.logo_filename)
        return None
    
    @app.template_global()
    def get_hero_icon_url(site_settings):
        """Get hero icon URL - either base64 data URL or file URL"""
        if site_settings and site_settings.hero_icon_base64:
            return site_settings.hero_icon_base64
        elif site_settings and site_settings.hero_icon_filename:
            return url_for('static', filename='uploads/' + site_settings.hero_icon_filename)
        return None
    
    # Warn (but never fail) if settings encryption is unavailable - the app must
    # stay up; only payments degrade. See services/crypto.py.
    encryption_state, encryption_message = encryption_status()
    if encryption_state != 'ok':
        print(f"WARNING: {encryption_message} - encrypted settings unavailable, Stripe payments disabled")

    # Handle PostgreSQL URL for Render.com
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///chatbot_platform.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Documents now live in object storage. This path is only consulted for
    # legacy rows that still carry a file_path from before that move.
    app.config['UPLOAD_FOLDER'] = os.environ.get('LOCAL_STORAGE_PRIVATE_DIR') or 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

    # Create upload directory if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('services', exist_ok=True)

    configure_logging(app)

    if database_url.startswith('sqlite'):
        # Local dev only: the training thread and a request can now write at the
        # same time, and SQLite's default is to fail instantly rather than wait
        # for the writer lock.
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 30}}

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    
    # Enable CORS for all routes to allow embedded chatbots on external websites
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # Initialize services
    document_processor = DocumentProcessor()
    chatbot_trainer = get_trainer()

    # Initialize chat service lazily to avoid startup errors
    chat_service = None

    def get_chat_service():
        nonlocal chat_service
        if chat_service is None:
            try:
                chat_service = ChatServiceOpenAI()
            except ValueError as e:
                print(f"WARNING: {e}")
                print("INFO: OpenAI service not available. Some features may be limited.")
                return None
        return chat_service

    # Routes

    @app.before_request
    def start_request_log():
        g.request_id = uuid.uuid4().hex[:12]
        g.request_started = time.monotonic()

    @app.after_request
    def finish_request_log(response):
        started = getattr(g, 'request_started', None)
        request_id = getattr(g, 'request_id', None)
        if request_id:
            # Echoed to the browser so a user-reported failure maps to a log line.
            response.headers['X-Request-Id'] = request_id
        if started is None:
            return response

        ms = int((time.monotonic() - started) * 1000)
        status = response.status_code
        quiet = request.path.startswith(QUIET_PATH_PREFIXES)
        slow = ms >= SLOW_REQUEST_MS

        if status >= 500:
            level = logging.ERROR
        elif status >= 400 or slow:
            level = logging.WARNING
        elif quiet or request.method == 'GET':
            level = logging.DEBUG
        else:
            level = logging.INFO

        fields = {'method': request.method, 'path': request.path,
                  'status': status, 'ms': ms}
        if slow:
            fields['slow'] = True
        if request.content_length:
            fields['content_length'] = request.content_length
        request_logger().event('http.request', level=level, **fields)
        return response

    @app.teardown_request
    def log_request_exception(error):
        # Only set for an exception that escaped the view; the response has
        # already been turned into a 500 by the time this runs.
        if error is None:
            return
        request_logger().error('http.exception', method=request.method,
                               path=request.path,
                               error=f'{type(error).__name__}: {error}',
                               exc_info=True)

    @app.errorhandler(413)
    def handle_payload_too_large(error):
        """Werkzeug aborts mid-body on MAX_CONTENT_LENGTH, which reaches the
        browser as a dead connection rather than a message. Say so instead."""
        limit_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        request_logger().warning('http.payload_too_large', path=request.path,
                                 content_length=request.content_length,
                                 limit_mb=limit_mb)
        message = (f'That file is larger than the {limit_mb}MB upload limit. '
                   f'Please upload a smaller file.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': message}), 413
        flash(message, 'error')
        return redirect(request.referrer or url_for('index'))

    @app.before_request
    def attach_user_plan_to_current_user():
        # Ensure templates like plans can read current_user.user_plan reliably
        try:
            if current_user.is_authenticated:
                try:
                    current_user.user_plan = get_user_plan(current_user)
                except Exception:
                    current_user.user_plan = None
            else:
                # Attribute exists but is None when anonymous
                current_user.user_plan = None
        except Exception:
            pass

    @app.route('/')
    def index():
        # Get homepage chatbot settings
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        # Get active homepage sections ordered by order field
        homepage_sections = HomepageSection.query.filter_by(is_active=True).order_by(HomepageSection.order.asc(), HomepageSection.created_at.asc()).all()
        
        return render_template('index.html',
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder,
                             homepage_sections=homepage_sections)

    @app.route('/health')
    def health_check():
        """Health check endpoint for Railway"""
        try:
            # Check database connection
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            db_status = "connected"
        except Exception as e:
            print(f"Database health check failed: {e}")
            db_status = "error"
        
        # Where files are going is an operational fact worth checking from
        # outside the box. Configuration only, no network call: Render polls
        # this endpoint, and a storage blip must not mark the service unhealthy
        # and trigger a restart loop. Live probing is behind ?deep=1.
        try:
            storage = describe_storage()
            if request.args.get('deep') == '1':
                from services.object_storage import check_storage
                storage['probe'] = check_storage()
        except Exception as e:
            storage = {'error': str(e)}

        health_data = {
            'status': 'healthy',
            'service': 'ChatBot Platform',
            'database': db_status,
            'storage': storage,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(health_data), 200

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        if request.method == 'POST':
            # Contact form is temporarily disabled during development
            flash('The contact form is temporarily disabled. Please use the email address provided on this page to reach us directly.', 'info')
            return redirect(url_for('contact'))
            
            # Email sending functionality is temporarily disabled
            # Change the condition below from False to True to re-enable the contact form
            if False:  # Set to True to re-enable email sending
                name = request.form.get('name', '').strip()
                email = request.form.get('email', '').strip()
                subject = request.form.get('subject', '').strip()
                message = request.form.get('message', '').strip()
                
                # Basic validation
                if not name or not email or not subject or not message:
                    flash('All fields are required.', 'error')
                # Get active FAQ items for error case
                faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                
                # Get homepage chatbot settings for chatbot display
                homepage_chatbot_id = get_setting('homepage_chatbot_id')
                homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
                homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                
                # Get the chatbot details if configured
                homepage_chatbot = None
                if homepage_chatbot_id:
                    homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
                
                # Fallback to demo chatbot if no specific one is configured
                if not homepage_chatbot:
                    homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
                
                return render_template('contact.html', 
                                     faqs=faqs,
                                     homepage_chatbot=homepage_chatbot,
                                     homepage_chatbot_title=homepage_chatbot_title,
                                     homepage_chatbot_placeholder=homepage_chatbot_placeholder)
                
                # Email validation
                if '@' not in email or '.' not in email:
                    flash('Please enter a valid email address.', 'error')
                    # Get active FAQ items for error case
                    faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                    
                    # Get homepage chatbot settings for chatbot display
                    homepage_chatbot_id = get_setting('homepage_chatbot_id')
                    homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
                    homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                    
                    # Get the chatbot details if configured
                    homepage_chatbot = None
                    if homepage_chatbot_id:
                        homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
                    
                    # Fallback to demo chatbot if no specific one is configured
                    if not homepage_chatbot:
                        homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
                    
                    return render_template('contact.html', 
                                         faqs=faqs,
                                         homepage_chatbot=homepage_chatbot,
                                         homepage_chatbot_title=homepage_chatbot_title,
                                         homepage_chatbot_placeholder=homepage_chatbot_placeholder)
                
                try:
                    # Create email content
                    email_subject = f"Contact Form: {subject}"
                    email_body = f"""
New contact form submission from {name} ({email})

Subject: {subject}

Message:
{message}

---
Sent from Chatbot Platform Contact Form
Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
                    """
                    
                    # Send email to admin
                    admin_email = os.getenv('RESEND_ADMIN_EMAIL')
                    if not admin_email:
                        flash('Admin email not configured. Please contact the administrator.', 'error')
                        # Get active FAQ items for error case
                        faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                        
                        # Get homepage chatbot settings for chatbot display
                        homepage_chatbot_id = get_setting('homepage_chatbot_id')
                        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
                        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                        
                        # Get the chatbot details if configured
                        homepage_chatbot = None
                        if homepage_chatbot_id:
                            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
                        
                        # Fallback to demo chatbot if no specific one is configured
                        if not homepage_chatbot:
                            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
                        
                        return render_template('contact.html', 
                                             faqs=faqs,
                                             homepage_chatbot=homepage_chatbot,
                                             homepage_chatbot_title=homepage_chatbot_title,
                                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)
                    
                    send_email(admin_email, email_subject, email_body)
                    
                    # Send confirmation email to user
                    from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
                    confirmation_subject = "Thank you for contacting us"
                    confirmation_body = f"""
Dear {name},

Thank you for contacting us. We have received your message and will get back to you as soon as possible.

Your message:
Subject: {subject}
Message: {message}

Best regards,
{from_name}
                    """
                    
                    send_email(email, confirmation_subject, confirmation_body)
                    
                    flash('Thank you for your message! We will get back to you soon.', 'success')
                    return redirect(url_for('contact'))
                    
                except Exception as e:
                    flash(f'Failed to send message. Please try again later. Error: {str(e)}', 'error')
                    # Get active FAQ items for error case
                    faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                    
                    # Get homepage chatbot settings for chatbot display
                    homepage_chatbot_id = get_setting('homepage_chatbot_id')
                    homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
                    homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                    
                    # Get the chatbot details if configured
                    homepage_chatbot = None
                    if homepage_chatbot_id:
                        homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
                    
                    # Fallback to demo chatbot if no specific one is configured
                    if not homepage_chatbot:
                        homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
                    
                    return render_template('contact.html', 
                                         faqs=faqs,
                                         homepage_chatbot=homepage_chatbot,
                                         homepage_chatbot_title=homepage_chatbot_title,
                                         homepage_chatbot_placeholder=homepage_chatbot_placeholder)
        
        # Get active FAQ items ordered by order field
        faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
        
        # Get homepage chatbot settings for chatbot display
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        return render_template('contact.html', 
                             faqs=faqs,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/plans')
    def plans():
        plans = Plan.query.filter_by(is_active=True).order_by(Plan.monthly_price.asc()).all()
        
        # Get homepage chatbot settings for chatbot display
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        return render_template('plans.html', 
                             plans=plans,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            username = request.form['username']
            email = request.form['email']
            password = request.form['password']
            business_name = request.form.get('business_name', '').strip()
            website = request.form.get('website', '').strip()
            
            if User.query.filter_by(username=username).first():
                flash('Username already exists')
                return redirect(url_for('register'))
            
            if User.query.filter_by(email=email).first():
                flash('Email already exists')
                return redirect(url_for('register'))
            
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                business_name=business_name if business_name else None,
                website=website if website else None
            )
            
            db.session.add(user)
            db.session.commit()
            
            login_user(user)
            flash('Registration successful!')
            return redirect(url_for('dashboard'))
        
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            user = User.query.filter_by(username=username).first()
            
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password')
        
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'POST':
            email = request.form.get('email', '').strip()
            
            if not email:
                flash('Please enter your email address.', 'error')
                return render_template('forgot_password.html')
            
            # Find user by email
            user = User.query.filter_by(email=email).first()
            
            if user:
                try:
                    # Generate reset token
                    token = generate_password_reset_token(user)
                    
                    # Send reset email
                    send_password_reset_email(user, token)
                    
                    flash('Password reset instructions have been sent to your email address.', 'success')
                    return redirect(url_for('login'))
                    
                except Exception as e:
                    flash(f'Failed to send reset email. Please try again later. Error: {str(e)}', 'error')
                    return render_template('forgot_password.html')
            else:
                # Don't reveal if email exists or not for security
                flash('If an account with that email exists, password reset instructions have been sent.', 'info')
                return redirect(url_for('login'))
        
        return render_template('forgot_password.html')

    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        # Find the token
        reset_token = PasswordResetToken.query.filter_by(token=token, used=False).first()
        
        if not reset_token:
            flash('Invalid or expired reset token.', 'error')
            return redirect(url_for('login'))
        
        # Check if token is expired
        if datetime.utcnow() > reset_token.expires_at:
            flash('Reset token has expired. Please request a new password reset.', 'error')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            # Validate passwords
            if not password or not confirm_password:
                flash('Please fill in all fields.', 'error')
                return render_template('reset_password.html', token=token)
            
            if password != confirm_password:
                flash('Passwords do not match.', 'error')
                return render_template('reset_password.html', token=token)
            
            if len(password) < 6:
                flash('Password must be at least 6 characters long.', 'error')
                return render_template('reset_password.html', token=token)
            
            try:
                # Update user password
                user = reset_token.user
                user.password_hash = generate_password_hash(password)
                
                # Mark token as used
                reset_token.used = True
                
                db.session.commit()
                
                flash('Your password has been reset successfully. You can now log in with your new password.', 'success')
                return redirect(url_for('login'))
                
            except Exception as e:
                flash(f'Failed to reset password. Please try again later. Error: {str(e)}', 'error')
                return render_template('reset_password.html', token=token)
        
        return render_template('reset_password.html', token=token)

    @app.route('/dashboard')
    @login_required
    def dashboard():
        chatbots = Chatbot.query.filter_by(user_id=current_user.id).all()
        # Attach user_plan attribute for templates that may rely on it
        try:
            current_user.user_plan = get_user_plan(current_user)
        except Exception:
            current_user.user_plan = None
        current_chatbot_count = len(chatbots)
        remaining_chatbots = (current_user.user_plan.chatbot_limit - current_chatbot_count) if current_user.user_plan else 0
        
        # Get homepage chatbot settings for chatbot display
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        usage_summary = get_usage_summary(current_user)
        return render_template('dashboard.html', 
                             chatbots=chatbots,
                             usage_summary=usage_summary,
                             user_plan=current_user.user_plan,
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        if request.method == 'POST':
            # Handle profile updates
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            full_name = request.form.get('full_name', '').strip()
            business_name = request.form.get('business_name', '').strip()
            website = request.form.get('website', '').strip()
            current_password = request.form.get('current_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            # Validate required fields
            if not username or not email:
                flash('Username and email are required.', 'error')
                return render_template('profile.html')
            
            # Check if username is already taken by another user
            existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
            if existing_user:
                flash('Username is already taken.', 'error')
                return render_template('profile.html')
            
            # Check if email is already taken by another user
            existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
            if existing_email:
                flash('Email is already taken.', 'error')
                return render_template('profile.html')
            
            # Update basic profile info
            current_user.username = username
            current_user.email = email
            current_user.full_name = full_name if full_name else None
            current_user.business_name = business_name if business_name else None
            current_user.website = website if website else None
            
            # Handle password change if provided
            if new_password:
                if not current_password:
                    flash('Current password is required to change password.', 'error')
                    return render_template('profile.html')
                
                # Verify current password
                if not check_password_hash(current_user.password_hash, current_password):
                    flash('Current password is incorrect.', 'error')
                    return render_template('profile.html')
                
                if new_password != confirm_password:
                    flash('New passwords do not match.', 'error')
                    return render_template('profile.html')
                
                if len(new_password) < 6:
                    flash('New password must be at least 6 characters long.', 'error')
                    return render_template('profile.html')
                
                # Update password
                current_user.password_hash = generate_password_hash(new_password)
                flash('Password updated successfully.', 'success')
            
            try:
                db.session.commit()
                flash('Profile updated successfully.', 'success')
                return redirect(url_for('profile'))
            except Exception as e:
                db.session.rollback()
                flash(f'Failed to update profile. Please try again. Error: {str(e)}', 'error')
                return render_template('profile.html')
        
        return render_template('profile.html')

    @app.route('/create_chatbot', methods=['GET', 'POST'])
    @login_required
    def create_chatbot():
        if request.method == 'POST':
            # Check chatbot limit for user's plan
            user_plan = get_user_plan(current_user)
            current_chatbot_count = Chatbot.query.filter_by(user_id=current_user.id).count()
            
            if current_chatbot_count >= user_plan.chatbot_limit:
                flash(f'You have reached your plan limit of {user_plan.chatbot_limit} chatbots. Please upgrade your plan to create more chatbots.', 'warning')
                return redirect(url_for('create_chatbot'))
            
            name = request.form['name']
            description = request.form['description']
            system_prompt = request.form.get('system_prompt', '').strip()
            greeting_message = request.form.get('greeting_message', '').strip()
            
            # The picker only offers what the plan allows, but the form is just
            # HTML - re-check server side so a forged POST cannot buy a tier.
            allowed_models = get_allowed_models(user_plan)
            model_alias = (request.form.get('model_alias') or '').strip().lower()
            if not model_alias:
                model_alias = model_catalog.cheapest_allowed(allowed_models)
            elif model_alias not in allowed_models:
                flash('That AI model is not available on your current plan. '
                      'Please upgrade your plan or choose another model.', 'error')
                return redirect(url_for('create_chatbot'))
            
            # Validate chatbot name
            is_valid, error_message = is_valid_chatbot_name(name)
            if not is_valid:
                flash(error_message, 'error')
                return redirect(url_for('create_chatbot'))
            
            # Generate URL-friendly name
            url_name = generate_url_name(name)
            if not url_name:
                flash('Chatbot name must contain at least one letter or number', 'error')
                return redirect(url_for('create_chatbot'))
            
            # Check if URL name already exists for this user
            existing_chatbot = Chatbot.query.filter_by(user_id=current_user.id, url_name=url_name).first()
            if existing_chatbot:
                flash('A chatbot with this name already exists. Please choose a different name.', 'error')
                return redirect(url_for('create_chatbot'))
            
            # Use default prompt if none provided
            if not system_prompt:
                system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
            
            # Handle avatar selection (custom upload or predefined)
            avatar_filename = None
            
            # Check for predefined avatar selection first
            selected_avatar = request.form.get('selected_avatar')
            if selected_avatar:
                # Validate that the selected avatar exists in our predefined avatars
                allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
                if selected_avatar in allowed_predefined:
                    avatar_filename = selected_avatar
                else:
                    flash('Invalid predefined avatar selection.', 'error')
                    return redirect(url_for('create_chatbot'))
            
            # If no predefined avatar selected, check for custom upload
            elif 'avatar' in request.files:
                avatar_file = request.files['avatar']
                if avatar_file and avatar_file.filename:
                    # Check if file is allowed
                    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                    if '.' in avatar_file.filename and \
                       avatar_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                        
                        try:
                            avatar_filename = store_avatar(avatar_file)
                        except StorageError as error:
                            request_logger().error('avatar.failed', on='create',
                                                   code=error.code, status=error.status,
                                                   attempts=error.attempts,
                                                   error=str(error))
                            flash(friendly_error(error.code), 'error')
                            return redirect(url_for('create_chatbot'))
                    else:
                        flash('Invalid avatar file type. Please upload PNG, JPG, GIF, or SVG files.', 'error')
                        return redirect(url_for('create_chatbot'))
            
            chatbot = Chatbot(
                name=name,
                url_name=url_name,
                description=description,
                system_prompt=system_prompt,
                embed_code=str(uuid.uuid4()),
                user_id=current_user.id,
                avatar_filename=avatar_filename,
                greeting_message=greeting_message if greeting_message else None,
                model_alias=model_alias
            )
            
            db.session.add(chatbot)
            db.session.commit()
            
            flash('Chatbot created successfully!')
            return redirect(url_for('chatbot_details_by_name', username=current_user.username, chatbot_name=chatbot.url_name))
        
        # Get user's plan info for display
        user_plan = get_user_plan(current_user)
        current_chatbot_count = Chatbot.query.filter_by(user_id=current_user.id).count()
        remaining_chatbots = user_plan.chatbot_limit - current_chatbot_count
        
        # Get homepage chatbot settings for chatbot display
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        allowed_models = get_allowed_models(user_plan)
        return render_template('create_chatbot.html', 
                             user_plan=user_plan, 
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots,
                             model_profiles=model_catalog.selectable_profiles(),
                             allowed_models=allowed_models,
                             default_model_alias=model_catalog.cheapest_allowed(allowed_models),
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/<username>/<chatbot_name>')
    @login_required
    def chatbot_details_by_name(username, chatbot_name):
        # Find user by username
        user = User.query.filter_by(username=username).first_or_404()
        
        # Find chatbot by url_name and user_id
        chatbot = Chatbot.query.filter_by(url_name=chatbot_name, user_id=user.id).first_or_404()
        
        # Check if current user has access (owner or admin)
        if chatbot.user_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to access this chatbot.', 'error')
            return redirect(url_for('dashboard'))
        
        documents = Document.query.filter_by(chatbot_id=chatbot.id).all()
        conversations = Conversation.query.filter_by(chatbot_id=chatbot.id).order_by(Conversation.timestamp.desc()).limit(50).all()
        
        # Get usage tracking data
        usage_data = ChatbotUsage.query.filter_by(chatbot_id=chatbot.id, is_active=True).order_by(ChatbotUsage.last_seen.desc()).all()
        
        # Get homepage chatbot settings
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get homepage chatbot
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        # Rendered into the page so a reload during training resumes polling
        # instead of showing a stale "Not Trained" state.
        active_run = training_runner.active_run_for_chatbot(chatbot.id)
        last_run = training_runner.latest_run_for_chatbot(chatbot.id)
        
        return render_template('chatbot_details.html', 
                             chatbot=chatbot, 
                             documents=documents, 
                             conversations=conversations,
                             usage_data=usage_data,
                             model_profiles=model_catalog.selectable_profiles(),
                             allowed_models=get_allowed_models(current_user.user_plan),
                             effective_model_alias=resolve_model_for_chatbot(chatbot),
                             active_run=active_run,
                             active_run_json=json.dumps(training_runner.run_to_dict(active_run)),
                             last_run=last_run,
                             last_training_error=(friendly_error(last_run.error_code)
                                                  if last_run and last_run.error_code else None),
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/chatbot/<int:chatbot_id>')
    @login_required
    def chatbot_details(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
        conversations = Conversation.query.filter_by(chatbot_id=chatbot_id).order_by(Conversation.timestamp.desc()).limit(50).all()
        
        # Get usage tracking data
        usage_data = ChatbotUsage.query.filter_by(chatbot_id=chatbot_id, is_active=True).order_by(ChatbotUsage.last_seen.desc()).all()
        
        # Get homepage chatbot settings
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get homepage chatbot
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        # Rendered into the page so a reload during training resumes polling
        # instead of showing a stale "Not Trained" state.
        active_run = training_runner.active_run_for_chatbot(chatbot.id)
        last_run = training_runner.latest_run_for_chatbot(chatbot.id)
        
        return render_template('chatbot_details.html', 
                             chatbot=chatbot, 
                             documents=documents, 
                             conversations=conversations,
                             usage_data=usage_data,
                             model_profiles=model_catalog.selectable_profiles(),
                             allowed_models=get_allowed_models(current_user.user_plan),
                             effective_model_alias=resolve_model_for_chatbot(chatbot),
                             active_run=active_run,
                             active_run_json=json.dumps(training_runner.run_to_dict(active_run)),
                             last_run=last_run,
                             last_training_error=(friendly_error(last_run.error_code)
                                                  if last_run and last_run.error_code else None),
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/chatbot/<int:chatbot_id>/analytics')
    @login_required
    def chatbot_analytics(chatbot_id):
        """Display analytics for a chatbot's conversations.

        Admins reach this from the admin area for any bot; everyone else only
        ever sees their own. A non-admin asking for someone else's bot still
        gets the same 404 as before, so the route never confirms that an id
        exists for a user who has no business with it.
        """
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        is_admin_view = chatbot.user_id != current_user.id
        if is_admin_view and not current_user.is_admin:
            abort(404)

        # Get conversations from the last 30 days only
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        conversations = Conversation.query.filter(
            Conversation.chatbot_id == chatbot_id,
            Conversation.timestamp >= thirty_days_ago
        ).order_by(Conversation.timestamp.desc()).all()
        
        # Initialize analytics service
        analytics_service = AnalyticsService()
        
        # Get analytics data. Keyword extraction costs tokens, so it draws on
        # the same allowance - once the owner is over it, fall back to the local
        # extractor rather than failing the page. The allowance is read from the
        # OWNER, not current_user, because record_token_usage() below bills the
        # owner: an admin viewing someone else's bot must neither spend from nor
        # be blocked by their own quota.
        owner = chatbot.owner or User.query.get(chatbot.user_id)
        analytics_allowed, _message = check_token_allowance_for_user(owner)
        analytics_usage = []
        analytics_data = analytics_service.get_conversation_analytics(
            conversations, usage_sink=analytics_usage, allow_ai=analytics_allowed)
        
        for usage in analytics_usage:
            record_token_usage(chatbot.user_id, chatbot.id, usage, source='analytics')
        
        # Get homepage chatbot settings (for platform assistant)
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get homepage chatbot
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        return render_template('analytics.html',
                             chatbot=chatbot,
                             analytics=analytics_data,
                             is_admin_view=is_admin_view,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/chatbot/<int:chatbot_id>/update', methods=['POST'])
    @login_required
    def update_chatbot(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        description = request.form.get('description', '').strip()
        system_prompt = request.form.get('system_prompt', '').strip()
        greeting_message = request.form.get('greeting_message', '').strip()
        homepage_url = request.form.get('homepage_url', '').strip()
        contact_us_url = request.form.get('contact_us_url', '').strip()
        
        # Same server-side re-check as on create. An absent field means an older
        # cached form, so leave the existing choice alone rather than clearing it.
        model_alias = (request.form.get('model_alias') or '').strip().lower()
        if model_alias:
            if model_alias not in get_allowed_models(get_user_plan(current_user)):
                flash('That AI model is not available on your current plan.', 'error')
                return redirect(get_chatbot_url(chatbot))
            chatbot.model_alias = model_alias
        
        # Update fields
        chatbot.description = description if description else None
        chatbot.greeting_message = greeting_message if greeting_message else None
        chatbot.homepage_url = homepage_url if homepage_url else None
        chatbot.contact_us_url = contact_us_url if contact_us_url else None
        
        if system_prompt:
            chatbot.system_prompt = system_prompt
        else:
            chatbot.system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
        
        # Handle avatar selection (custom upload or predefined)
        selected_avatar = request.form.get('selected_avatar')
        if selected_avatar:
            # Validate that the selected avatar exists in our predefined avatars
            allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
            if selected_avatar in allowed_predefined:
                # Delete old custom avatar if exists (only if it's not a predefined one)
                delete_avatar(chatbot.avatar_filename)
                
                chatbot.avatar_filename = selected_avatar
            else:
                flash('Invalid predefined avatar selection.', 'error')
                return redirect(get_chatbot_url(chatbot))
        
        elif 'avatar' in request.files:
            avatar_file = request.files['avatar']
            if avatar_file and avatar_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in avatar_file.filename and \
                   avatar_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    
                    # Upload the new one first; only drop the old one once the
                    # replacement is safely stored.
                    try:
                        new_avatar_filename = store_avatar(
                            avatar_file, logger=request_logger(chatbot_id=chatbot.id))
                    except StorageError as error:
                        request_logger(chatbot_id=chatbot.id).error(
                            'avatar.failed', on='update', code=error.code,
                            status=error.status, attempts=error.attempts,
                            error=str(error))
                        flash(friendly_error(error.code), 'error')
                        return redirect(get_chatbot_url(chatbot))
                    delete_avatar(chatbot.avatar_filename)
                    chatbot.avatar_filename = new_avatar_filename
                else:
                    flash('Invalid avatar file type. Please upload PNG, JPG, GIF, or SVG files.', 'error')
                    return redirect(get_chatbot_url(chatbot))
        
        db.session.commit()
        flash('Chatbot updated successfully!')
        
        return redirect(get_chatbot_url(chatbot))

    @app.route('/upload_document/<int:chatbot_id>', methods=['POST'])
    @login_required
    def upload_document(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()

        # Check if this is an Ajax request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        log = request_logger(chatbot_id=chatbot_id)
        # Logged before anything can go wrong, so an upload that never finishes
        # is still distinguishable from one that never arrived.
        log.event('upload.received', ajax=is_ajax,
                  content_length=request.content_length)

        if 'file' not in request.files:
            log.warning('upload.rejected', reason='no_file_field')
            if is_ajax:
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            flash('No file selected')
            return redirect(get_chatbot_url(chatbot))

        file = request.files['file']
        if file.filename == '':
            log.warning('upload.rejected', reason='empty_filename')
            if is_ajax:
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            flash('No file selected')
            return redirect(get_chatbot_url(chatbot))

        # For the rejection paths, which never get as far as a storage key.
        extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''

        if file and allowed_file(file.filename):
            # Check file size limit based on user's plan
            user_plan = get_user_plan(current_user)
            file_size_limit_bytes = user_plan.file_size_limit_mb * 1024 * 1024  # Convert MB to bytes
            
            # Get file size
            file.seek(0, 2)  # Seek to end of file
            file_size = file.tell()
            file.seek(0)  # Reset file pointer
            
            if file_size > file_size_limit_bytes:
                log.warning('upload.rejected', reason='over_plan_limit', ext=extension,
                            bytes=file_size, limit_mb=user_plan.file_size_limit_mb)
                error_msg = f'File size ({file_size / (1024*1024):.1f}MB) exceeds your plan limit ({user_plan.file_size_limit_mb}MB). Please upgrade your plan or use a smaller file.'
                if is_ajax:
                    return jsonify({'success': False, 'error': error_msg}), 400
                flash(error_msg, 'error')
                return redirect(get_chatbot_url(chatbot))
            
            filename = secure_filename(file.filename)
            
            # Check if a document with the same original filename already exists for this chatbot
            existing_document = Document.query.filter_by(
                original_filename=filename, 
                chatbot_id=chatbot_id
            ).first()
            
            if existing_document:
                # Drop the previous upload; best-effort, never fatal.
                delete_document_object(existing_document)
                
                # Update the existing document record. Upload first, commit
                # second: the reverse would leave a row pointing at nothing.
                try:
                    started = time.monotonic()
                    log.event('upload.storing', ext=extension, bytes=file_size,
                              replaces_document_id=existing_document.id)
                    unique_filename, key = store_document_bytes(
                        chatbot_id, filename, file.read(), file.mimetype, logger=log)
                    log.event('upload.stored', key=key, bytes=file_size,
                              ms=int((time.monotonic() - started) * 1000))

                    existing_document.filename = unique_filename
                    existing_document.storage_key = key
                    existing_document.uploaded_at = datetime.utcnow()
                    existing_document.processed = False  # Mark as unprocessed so it gets retrained
                    
                    db.session.commit()
                    
                    if is_ajax:
                        return jsonify({
                            'success': True,
                            'message': f'Document "{filename}" has been updated successfully!',
                            'document': {
                                'id': existing_document.id,
                                'original_filename': existing_document.original_filename,
                                'uploaded_at': existing_document.uploaded_at.strftime('%Y-%m-%d %H:%M'),
                                'processed': existing_document.processed
                            },
                            'is_update': True
                        })
                    flash(f'Document "{filename}" has been updated successfully!')
                except Exception as e:
                    db.session.rollback()
                    log.error('upload.failed', ext=extension, bytes=file_size,
                              is_update=True, code=getattr(e, 'code', None),
                              error=f'{type(e).__name__}: {e}', exc_info=True)
                    error_msg = f'Error saving file: {str(e)}. Please try again.'
                    if is_ajax:
                        return jsonify({'success': False, 'error': error_msg}), 500
                    flash(error_msg)
                    return redirect(get_chatbot_url(chatbot))
            else:
                # Create new document. Upload first, commit second.
                try:
                    started = time.monotonic()
                    log.event('upload.storing', ext=extension, bytes=file_size)
                    unique_filename, key = store_document_bytes(
                        chatbot_id, filename, file.read(), file.mimetype, logger=log)
                    log.event('upload.stored', key=key, bytes=file_size,
                              ms=int((time.monotonic() - started) * 1000))

                    document = Document(
                        filename=unique_filename,
                        original_filename=filename,
                        file_path='',          # legacy column, no longer written
                        storage_key=key,
                        chatbot_id=chatbot_id
                    )
                    
                    db.session.add(document)
                    db.session.commit()
                    
                    if is_ajax:
                        return jsonify({
                            'success': True,
                            'message': 'Document uploaded successfully!',
                            'document': {
                                'id': document.id,
                                'original_filename': document.original_filename,
                                'uploaded_at': document.uploaded_at.strftime('%Y-%m-%d %H:%M'),
                                'processed': document.processed
                            },
                            'is_update': False
                        })
                    flash('Document uploaded successfully!')
                except Exception as e:
                    db.session.rollback()
                    log.error('upload.failed', ext=extension, bytes=file_size,
                              is_update=False, code=getattr(e, 'code', None),
                              error=f'{type(e).__name__}: {e}', exc_info=True)
                    error_msg = f'Error saving file: {str(e)}. Please try again.'
                    if is_ajax:
                        return jsonify({'success': False, 'error': error_msg}), 500
                    flash(error_msg)
                    return redirect(get_chatbot_url(chatbot))
        else:
            log.warning('upload.rejected', reason='bad_extension', ext=extension)
            error_msg = 'Invalid file type. Please upload PDF, DOCX, TXT, JSON, or XLSX files.'
            if is_ajax:
                return jsonify({'success': False, 'error': error_msg}), 400
            flash(error_msg)
        
        if is_ajax:
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400
        return redirect(get_chatbot_url(chatbot))

    @app.route('/upload_google_doc/<int:chatbot_id>', methods=['POST'])
    @login_required
    def upload_google_doc(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        google_doc_url = request.form.get('google_doc_url', '').strip()
        
        if not google_doc_url:
            flash('Please enter a Google Docs URL')
            return redirect(get_chatbot_url(chatbot))
        
        try:
            # Fetch the Google Doc content
            text = document_processor.fetch_google_doc(google_doc_url)
            
            if not text:
                flash('The Google Doc appears to be empty.')
                return redirect(get_chatbot_url(chatbot))
            
            # Extract document ID for naming
            doc_id = document_processor.extract_google_doc_id(google_doc_url)
            original_filename = f"Google_Doc_{doc_id}.txt"
            
            # Check if a document with the same Google Doc ID already exists
            existing_document = Document.query.filter_by(
                original_filename=original_filename, 
                chatbot_id=chatbot_id
            ).first()
            
            # Store the extracted text
            data, size_error = check_text_size(text, current_user)
            if size_error:
                flash(size_error, 'error')
                return redirect(get_chatbot_url(chatbot))
            unique_filename, key = store_document_bytes(
                chatbot_id, original_filename, data, 'text/plain; charset=utf-8')

            if existing_document:
                delete_document_object(existing_document)

                # Update existing document
                existing_document.filename = unique_filename
                existing_document.storage_key = key
                existing_document.uploaded_at = datetime.utcnow()
                existing_document.processed = False
                
                db.session.commit()
                flash(f'Google Doc has been updated successfully!')
            else:
                # Create new document record
                document = Document(
                    filename=unique_filename,
                    original_filename=original_filename,
                    file_path='',
                    storage_key=key,
                    chatbot_id=chatbot_id
                )
                
                db.session.add(document)
                db.session.commit()
                
                flash('Google Doc imported successfully!')
                
        except Exception as e:
            flash(f'Error importing Google Doc: {str(e)}')
            print(f"Error importing Google Doc: {str(e)}")
        
        return redirect(get_chatbot_url(chatbot))

    @app.route('/upload_google_sheet/<int:chatbot_id>', methods=['POST'])
    @login_required
    def upload_google_sheet(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        google_sheet_url = request.form.get('google_sheet_url', '').strip()
        
        if not google_sheet_url:
            flash('Please enter a Google Sheets URL')
            return redirect(get_chatbot_url(chatbot))
        
        try:
            # Fetch the Google Sheet content (already formatted as JSON + text)
            text = document_processor.fetch_google_sheet(google_sheet_url)
            
            if not text:
                flash('The Google Sheet appears to be empty.')
                return redirect(get_chatbot_url(chatbot))
            
            # Extract sheet ID for naming
            sheet_id = document_processor.extract_google_sheet_id(google_sheet_url)
            original_filename = f"Google_Sheet_{sheet_id}.txt"
            
            # Check if a document with the same Google Sheet ID already exists
            existing_document = Document.query.filter_by(
                original_filename=original_filename, 
                chatbot_id=chatbot_id
            ).first()
            
            # Store the extracted text
            data, size_error = check_text_size(text, current_user)
            if size_error:
                flash(size_error, 'error')
                return redirect(get_chatbot_url(chatbot))
            unique_filename, key = store_document_bytes(
                chatbot_id, original_filename, data, 'text/plain; charset=utf-8')

            if existing_document:
                delete_document_object(existing_document)

                # Update existing document
                existing_document.filename = unique_filename
                existing_document.storage_key = key
                existing_document.uploaded_at = datetime.utcnow()
                existing_document.processed = False
                
                db.session.commit()
                flash(f'Google Sheet has been updated successfully!')
            else:
                # Create new document record
                document = Document(
                    filename=unique_filename,
                    original_filename=original_filename,
                    file_path='',
                    storage_key=key,
                    chatbot_id=chatbot_id
                )
                
                db.session.add(document)
                db.session.commit()
                
                flash('Google Sheet imported successfully!')
                
        except Exception as e:
            flash(f'Error importing Google Sheet: {str(e)}')
            print(f"Error importing Google Sheet: {str(e)}")
        
        return redirect(get_chatbot_url(chatbot))

    @app.route('/scrape_website/<int:chatbot_id>', methods=['POST'])
    @login_required
    def scrape_website(chatbot_id):
        """Handle website scraping and save as training document"""
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        website_url = request.form.get('website_url', '').strip()
        
        if not website_url:
            flash('Please enter a website URL')
            return redirect(get_chatbot_url(chatbot))
        
        try:
            # Scrape the website
            print(f"Starting website scrape for: {website_url}")
            text = document_processor.scrape_website(website_url, max_pages=50, timeout=120)
            
            if not text or len(text.strip()) < 100:
                flash('The website appears to be empty or inaccessible.')
                return redirect(get_chatbot_url(chatbot))
            
            # Extract domain for naming
            from urllib.parse import urlparse
            parsed_url = urlparse(website_url)
            domain = parsed_url.netloc.replace('www.', '')
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            original_filename = f"WebScrape_{domain}_{timestamp}.txt"
            
            # Check if a document with similar name already exists
            existing_document = Document.query.filter(
                Document.chatbot_id == chatbot_id,
                Document.original_filename.like(f"WebScrape_{domain}%")
            ).first()
            
            # Store the scraped text. The scraper pulls up to 50 pages, so
            # this is the one importer most likely to hit the plan limit.
            data, size_error = check_text_size(text, current_user)
            if size_error:
                flash(size_error, 'error')
                return redirect(get_chatbot_url(chatbot))
            unique_filename, key = store_document_bytes(
                chatbot_id, original_filename, data, 'text/plain; charset=utf-8')

            if existing_document:
                delete_document_object(existing_document)

                # Update existing document
                existing_document.filename = unique_filename
                existing_document.storage_key = key
                existing_document.uploaded_at = datetime.utcnow()
                existing_document.processed = False
                
                db.session.commit()
                flash(f'Website content has been updated successfully! Scraped from: {website_url}')
            else:
                # Create new document record
                document = Document(
                    filename=unique_filename,
                    original_filename=original_filename,
                    file_path='',
                    storage_key=key,
                    chatbot_id=chatbot_id
                )
                
                db.session.add(document)
                db.session.commit()
                
                flash(f'Website scraped successfully! Pages extracted from: {website_url}')
                
        except Exception as e:
            flash(f'Error scraping website: {str(e)}')
            print(f"Error scraping website: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return redirect(get_chatbot_url(chatbot))

    @app.route('/delete_document/<int:document_id>', methods=['POST'])
    @login_required
    def delete_document(document_id):
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        chatbot = Chatbot.query.filter_by(id=document.chatbot_id, user_id=current_user.id).first_or_404()
        
        try:
            # Delete the physical file if it exists
            delete_document_object(document)
            
            # Delete the document record from database
            db.session.delete(document)
            db.session.commit()
            
            # If chatbot was trained, mark it as needing retraining
            if chatbot.is_trained:
                chatbot.is_trained = False
                db.session.commit()
                flash('Document deleted successfully! The chatbot will need to be retrained.')
            else:
                flash('Document deleted successfully!')
                
        except Exception as e:
            flash(f'Error deleting document: {str(e)}')
        
        return redirect(get_chatbot_url(chatbot))

    @app.route('/download_document/<int:document_id>')
    @login_required
    def download_document(document_id):
        # Get the document
        document = Document.query.get_or_404(document_id)
        
        # Get the chatbot - admins can access any chatbot, regular users only their own
        if current_user.is_admin:
            chatbot = Chatbot.query.get_or_404(document.chatbot_id)
        else:
            chatbot = Chatbot.query.filter_by(id=document.chatbot_id, user_id=current_user.id).first_or_404()
        
        # Proxy the bytes rather than redirecting: the private zone has no
        # pull zone, and the object must stay behind the ownership check above.
        try:
            data = load_document_bytes(document)
        except StorageError as error:
            print(f"ERROR: could not read document {document.id}: {error}")
            flash('The file storage service is not responding. Please try again.')
            return redirect(get_chatbot_url(chatbot))

        if data is None:
            flash('File not found on server. Please re-upload the document.')
            return redirect(get_chatbot_url(chatbot))

        try:
            return send_file(
                BytesIO(data),
                as_attachment=True,
                download_name=document.original_filename,
                mimetype='application/octet-stream'
            )
        except Exception as e:
            flash(f'Error downloading file: {str(e)}')
            return redirect(get_chatbot_url(chatbot))

    @app.route('/train_chatbot/<int:chatbot_id>', methods=['POST'])
    @login_required
    def train_chatbot(chatbot_id):
        """Start a training run. Returns immediately - the work happens in a thread.

        This used to do the whole pipeline inline, which on one gunicorn worker
        with a 120s timeout meant long runs died with a 502 and blocked every
        embedded chat widget while they ran.
        """
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()

        def respond(payload, status, flash_message=None, category='message'):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(payload), status
            flash(flash_message or payload.get('error') or '', category)
            return redirect(get_chatbot_url(chatbot))

        # Training draws on the same monthly allowance as chat, so it is capped
        # too. The owner is logged in here, so say plainly what happened.
        allowed, _message = check_token_allowance_for_user(current_user)
        if not allowed:
            over_limit = ('You have used your monthly token allowance, so training is '
                          'paused until next month. Upgrade your plan for a larger allowance.')
            return respond({'success': False, 'error': over_limit}, 402, over_limit, 'warning')

        if not Document.query.filter_by(chatbot_id=chatbot_id).count():
            message = friendly_error('no_documents')
            return respond({'success': False, 'error': message, 'error_code': 'no_documents'},
                           400, message)

        # Fail here rather than burning a run row on something we already know
        # cannot work.
        if not os.getenv('OPENAI_API_KEY'):
            message = friendly_error('no_api_key')
            return respond({'success': False, 'error': message, 'error_code': 'no_api_key'},
                           503, message, 'error')

        try:
            run, created = training_runner.enqueue_training(app, chatbot.id, current_user.id)
        except Exception as error:
            print(f"ERROR: could not start training for chatbot {chatbot_id}: {error}")
            message = friendly_error('internal')
            return respond({'success': False, 'error': message, 'error_code': 'internal'},
                           500, message, 'error')

        payload = {
            'success': True,
            'run_id': run.run_id,
            'already_running': not created,
            'status_url': url_for('train_chatbot_status', chatbot_id=chatbot.id,
                                  run_id=run.run_id),
            'run': training_runner.run_to_dict(run),
        }
        # 409 for "already running" so the browser can attach to the existing run
        # instead of queueing a duplicate from a second tab.
        return respond(payload, 202 if created else 409,
                       'Training started - this page will update automatically.')

    @app.route('/train_chatbot/<int:chatbot_id>/status')
    @login_required
    def train_chatbot_status(chatbot_id):
        """Poll a training run. The browser drives its progress bar off this."""
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()

        # Cheap and self-throttled to once a minute. Piggy-backing on the poll
        # avoids needing a scheduler just to notice a restart killed a worker.
        try:
            training_runner.reap_stale_runs()
        except Exception as error:
            print(f"WARNING: stale-run reaper failed: {error}")

        requested = (request.args.get('run_id') or '').strip()
        if requested:
            run = training_runner.get_run(chatbot.id, requested)
        else:
            run = training_runner.latest_run_for_chatbot(chatbot.id)

        if run is None:
            return jsonify({'success': False, 'error': 'No training run found.'}), 404

        return jsonify({
            'success': True,
            'run': training_runner.run_to_dict(run),
            'chatbot': {
                'is_trained': bool(chatbot.is_trained),
                'last_trained_at': (chatbot.last_trained_at.isoformat(timespec='seconds') + 'Z'
                                    if chatbot.last_trained_at else None),
            },
        })

    @app.route('/delete_chatbot/<int:chatbot_id>', methods=['POST'])
    @login_required
    def delete_chatbot(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        # Delete associated files
        for document in chatbot.documents:
            try:
                delete_document_object(document)
            except Exception as e:
                print(f"Error deleting file {document.file_path}: {e}")
        
        # Delete custom avatar if exists (not predefined)
        delete_avatar(chatbot.avatar_filename)
        
        # Delete chatbot training data
        try:
            chatbot_trainer.delete_chatbot_data(chatbot_id)
        except Exception as e:
            print(f"Error deleting training data: {e}")
        
        # Delete chatbot usage tracking records
        try:
            ChatbotUsage.query.filter_by(chatbot_id=chatbot_id).delete()
        except Exception as e:
            print(f"Error deleting usage tracking: {e}")

        purge_training_runs(chatbot_id)
        detach_token_usage(chatbot_id)
        
        db.session.delete(chatbot)
        db.session.commit()
        
        flash('Chatbot deleted successfully!')
        return redirect(url_for('dashboard'))

    @app.route('/chatbot/<int:chatbot_id>/training-data')
    @login_required
    def chatbot_training_data(chatbot_id):
        """User view of their own chatbot training data JSON"""
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        try:
            # Get training data from ChatbotTrainer
            training_data = chatbot_trainer.get_training_data(
                chatbot_id, version=artifact_version(chatbot))
            
            if not training_data:
                # Check if chatbot is marked as trained but no training data exists
                if chatbot.is_trained:
                    trained_when = (chatbot.last_trained_at.strftime('%Y-%m-%d %H:%M UTC')
                                    if chatbot.last_trained_at else 'an unknown date')
                    error_msg = (f"Chatbot '{chatbot.name}' was trained on {trained_when}, but its "
                                 f"training data file is missing from the server. This happens when a "
                                 f"deploy replaces the container without a persistent disk. Retraining "
                                 f"the chatbot will rebuild it.")
                else:
                    error_msg = f"Chatbot '{chatbot.name}' has not been trained yet. Please upload documents and train the chatbot first."
                
                return jsonify({
                    'success': False, 
                    'error': error_msg,
                    'chatbot_name': chatbot.name,
                    'is_trained_in_db': chatbot.is_trained
                }), 404
            
            return jsonify({
                'success': True,
                'chatbot_name': chatbot.name,
                'chatbot_id': chatbot_id,
                'training_data': training_data_for_display(
                    training_data, request.args.get('include_vectors') == '1'),
                'is_knowledge_base': chatbot_trainer.is_knowledge_base_format(training_data)
            })
            
        except Exception as e:
            print(f"ERROR: Failed to load training data for chatbot {chatbot_id}: {e}")
            return jsonify({
                'success': False,
                'error': f'Failed to load training data: {str(e)}',
                'chatbot_name': chatbot.name
            }), 500

    @app.route('/api/track-usage/<embed_code>', methods=['POST'])
    def track_usage_api(embed_code):
        """API endpoint to manually track chatbot usage"""
        try:
            chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
            if not chatbot:
                return jsonify({'error': 'Chatbot not found'}), 404
            
            data = request.get_json()
            website_url = data.get('website_url') if data else request.headers.get('Referer')
            
            if website_url:
                track_chatbot_usage(chatbot.id, website_url)
                return jsonify({'success': True, 'message': 'Usage tracked successfully'})
            else:
                return jsonify({'error': 'No website URL provided'}), 400
                
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/chat/<embed_code>', methods=['POST'])
    def chat_api(embed_code):
        try:
            chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
            if not chatbot:
                return jsonify({'error': 'Chatbot not found. Please check the embed code.'}), 404
            
            # Allow chatbots with custom prompts to work even without training
            if not chatbot.is_trained and not chatbot.system_prompt:
                return jsonify({'error': 'Chatbot is not trained yet. Please upload documents and train the chatbot first, or set a system prompt.'}), 400
            
            # Track usage if referer is provided
            referer = request.headers.get('Referer')
            if referer:
                track_chatbot_usage(chatbot.id, referer)
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data received'}), 400
                
            # Check if this is an end conversation action
            action = data.get('action')
            if action == 'end_conversation':
                conversation_id = data.get('conversation_id')
                resolved = data.get('resolved', False)
                
                if conversation_id:
                    # Update conversation status in database
                    # Since conversation_id is a UUID string, we need to find conversations by chatbot_id
                    # and update the most recent ones or all conversations for this chatbot
                    conversations = Conversation.query.filter_by(chatbot_id=chatbot.id).all()
                    for conv in conversations:
                        conv.response_status = 'resolved' if resolved else 'active'
                    db.session.commit()
                    
                    return jsonify({
                        'success': True,
                        'message': 'Conversation status updated',
                        'conversation_id': conversation_id
                    })
                else:
                    return jsonify({'error': 'Conversation ID required for end conversation action'}), 400
            
            user_message = data.get('message', '').strip()
            conversation_id = data.get('conversation_id', None)
            
            if not user_message:
                return jsonify({'error': 'Message is required'}), 400
            
            # Monthly token cap. Deliberately placed after the end_conversation
            # branch - a blocked visitor must still be able to close their
            # conversation - and before any OpenAI client is constructed, so a
            # blocked request costs one indexed row read and no API call.
            allowed, block_message = check_token_allowance(chatbot)
            if not allowed:
                print(f"[INFO] chatbot {chatbot.id}: owner is over their monthly token allowance")
                # 200 with 'response', not 429 with 'error': embed.html reads
                # data.response only, so an error-shaped body renders blank there.
                # response_html so every 200 from this route has one shape.
                # block_message is admin-editable, so a stray '<' in it would
                # break the widget exactly like a model-authored one.
                return jsonify({
                    'response': reply_to_plain_text(block_message),
                    'response_html': sanitize_reply(block_message),
                    'conversation_id': conversation_id or str(uuid.uuid4()),
                    'limit_reached': True
                })
            
            # Generate conversation ID if not provided (for new conversations)
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
                print(f"🆕 DEBUG: Generated new conversation ID: {conversation_id}")
            else:
                print(f"🔄 DEBUG: Continuing conversation: {conversation_id}")
            
            print(f"🤖 Chat API: Processing message for chatbot {chatbot.id}: '{user_message}'")
            
            # Import and use the ChatService for better response handling
            try:
                from services.chat_service import ChatService
                print(f"[OK] Successfully imported ChatService")
                chat_service = ChatService()
                print(f"[OK] Successfully created ChatService instance")
            except Exception as e:
                print(f"[ERROR] Failed to import/create ChatService: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Service initialization failed: {str(e)}'}), 500
            
            # Try to use OpenAI service first, fallback to local chat service.
            # usage stays None on every path that did not bill an OpenAI call.
            usage = None
            embed_usage = []
            openai_service = get_chat_service()
            if openai_service and hasattr(openai_service, 'get_response_with_usage'):
                try:
                    print(f"🔄 Trying OpenAI service")
                    response, usage = openai_service.get_response_with_usage(
                        chatbot.id, user_message, conversation_id,
                        embed_usage_sink=embed_usage)
                    print(f"[OK] OpenAI response generated")
                except Exception as e:
                    print(f"[WARNING] OpenAI service failed: {e}, falling back to local chat service")
                    try:
                        response = chat_service.get_response(chatbot.id, user_message)
                        usage = None
                        print(f"[OK] Local chat service response generated")
                    except Exception as e2:
                        print(f"[ERROR] Local chat service also failed: {e2}")
                        return jsonify({'error': f'Both services failed. OpenAI: {str(e)}, Local: {str(e2)}'}), 500
            else:
                # Use local chat service (better than direct trainer)
                print(f"🔄 Using local chat service")
                try:
                    response = chat_service.get_response(chatbot.id, user_message)
                    print(f"[OK] Local chat service response generated")
                except Exception as e:
                    print(f"[ERROR] Local chat service failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return jsonify({'error': f'Chat service failed: {str(e)}'}), 500
            
            # Ensure response is not None or empty
            if not response or response.strip() == "":
                response = "I'm sorry, I couldn't generate a proper response. Please try asking your question differently."

            # The model's reply is untrusted markup. The system prompt and the
            # scraped knowledge base can both put raw <a class="..."> in it, and
            # _format_plan_information adds <h3>/<b> of its own - so sanitize
            # once, here, and no client has to guess. See services/reply_sanitizer.py.
            sanitize_stats = {}
            response_html = sanitize_reply(response, stats_sink=sanitize_stats)
            response_text = reply_to_plain_text(response)
            if not response_html.strip():
                # A reply that was *entirely* markup sanitizes to nothing, and
                # the empty-check above ran before we knew that.
                response_html = response_text = (
                    "I'm sorry, I couldn't generate a proper response. "
                    "Please try asking your question differently.")
            request_logger(chatbot_id=chatbot.id).debug('chat.reply_sanitized',
                                                        **sanitize_stats)

            # Save conversation, with the per-request token ledger
            model_alias = None
            try:
                model_alias = resolve_model_for_chatbot(chatbot)
            except Exception:
                pass
            
            conversation = Conversation(
                chatbot_id=chatbot.id,
                user_message=user_message,
                bot_response=response,
                model_alias=model_alias,
                prompt_tokens=(usage or {}).get('prompt_tokens'),
                completion_tokens=(usage or {}).get('completion_tokens'),
                total_tokens=(usage or {}).get('total_tokens')
            )
            db.session.add(conversation)
            db.session.commit()
            
            # Roll the spend up onto the owner's monthly counter. Best effort -
            # a metering failure must never turn a good answer into a 500.
            if usage or embed_usage:
                try:
                    if usage:
                        record_token_usage(chatbot.user_id, chatbot.id, usage, source='chat')
                    # Query embeddings are metered separately, so the usage
                    # breakdown shows what retrieval costs apart from what
                    # answering costs.
                    for embed_item in embed_usage:
                        record_token_usage(chatbot.user_id, chatbot.id, embed_item,
                                           source='embedding')
                except Exception as e:
                    print(f"[WARNING] could not record token usage: {e}")
            
            print(f"💬 Response: {response[:100]}...")
            # 'response' stays plain text so a widget cached from before this
            # change keeps getting exactly what its old link regex expects;
            # 'response_html' is what current clients render.
            return jsonify({'response': response_text,
                            'response_html': response_html,
                            'conversation_id': conversation_id})
            
        except Exception as e:
            print(f"[ERROR] Chat API Error: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            
            # More detailed error information
            error_details = {
                'error': 'Sorry, I encountered an error. Please try again.',
                'debug_info': str(e) if app.debug else None
            }
            
            return jsonify(error_details), 500

    @app.route('/embed/<embed_code>')
    def embed_code(embed_code):
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        return render_template('embed.html', embed_code=embed_code, chatbot=chatbot)

    @app.route('/test-embed')
    def test_embed():
        # Get the first available chatbot for testing
        chatbot = Chatbot.query.first()
        if chatbot:
            return render_template('embed.html', embed_code=chatbot.embed_code, chatbot=chatbot)
        return "No chatbots available for testing"
    
    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        """Serve a custom chatbot avatar.

        This rule must exist forever: customers pasted absolute
        https://<host>/uploads/<file> URLs into their own sites when they copied
        an embed snippet, and we cannot edit those pages. Where the bytes live
        may change; this URL may not.
        """
        # The filename becomes a storage key, so this is a real traversal check.
        if not filename or secure_filename(filename) != filename:
            abort(404)

        storage = get_storage()
        key = avatar_key(filename)

        cdn_url = storage.public_url(PUBLIC, key)
        if cdn_url:
            # 302, never 301: a permanent redirect is cached by browsers
            # indefinitely, and these URLs live on pages we cannot fix. Keeping
            # it temporary keeps the mapping ours to change.
            response = redirect(cdn_url, code=302)
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response

        # No CDN (Bunny without a pull zone, or the local backend): proxy the
        # bytes. Deliberately one path for both, rather than a send_from_directory
        # special case reading a directory the backend may not be writing to.
        try:
            data = storage.get(PUBLIC, key)
        except StorageNotFound:
            abort(404)
        except StorageError as error:
            request_logger().error('avatar.fetch_failed', avatar=filename,
                                   code=error.code, status=error.status,
                                   error=str(error))
            print(f"WARNING: avatar fetch failed for {filename}: {error}")
            abort(502)
        mimetype, _ = mimetypes.guess_type(filename)
        response = Response(data, mimetype=mimetype or 'application/octet-stream')
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    
    @app.route('/preview/<embed_code>')
    def preview_chatbot(embed_code):
        """Preview chatbot on a sample business website"""
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        return render_template('preview.html', embed_code=embed_code, chatbot=chatbot)
    
    @app.route('/web-preview/<embed_code>')
    def web_preview_chatbot(embed_code):
        """Web preview chatbot on user's actual business website"""
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        
        # Determine which URL to use: homepage_url first, then fall back to owner's website
        website_url = chatbot.homepage_url or chatbot.owner.website
        
        # Check if we have a website URL
        if not website_url:
            return render_template('web_preview_no_website.html', chatbot=chatbot)
        
        return render_template('web_preview.html', embed_code=embed_code, chatbot=chatbot, website_url=website_url)
    
    @app.route('/create-demo-chatbot')
    def create_demo_route():
        """Manual route to create/recreate the demo chatbot"""
        try:
            demo_chatbot = create_demo_chatbot_internal()
            return jsonify({
                'success': True,
                'message': 'Demo chatbot created/updated successfully',
                'embed_code': demo_chatbot.embed_code,
                'is_trained': demo_chatbot.is_trained
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/debug-chat-service')
    def debug_chat_service():
        """Debug endpoint to check chat service functionality"""
        try:
            from services.chat_service import ChatService
            from services.chatbot_trainer import get_trainer
            
            # Test imports
            chat_service = ChatService()
            trainer = get_trainer()
            
            # Check methods
            trainer_methods = [method for method in dir(trainer) if not method.startswith('_')]
            chat_service_methods = [method for method in dir(chat_service) if not method.startswith('_')]
            
            return jsonify({
                'success': True,
                'chatbot_trainer_methods': trainer_methods,
                'chat_service_methods': chat_service_methods,
                'trainer_has_search_chunks': hasattr(trainer, 'search_chunks'),
                'chat_service_has_get_response': hasattr(chat_service, 'get_response')
            })
        except Exception as e:
            import traceback
            return jsonify({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }), 500

    # Admin Routes
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.is_admin and check_password_hash(user.password_hash, password):
                login_user(user)
                flash('Admin login successful!')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid admin credentials')
        
        return render_template('admin/login.html')

    @app.route('/admin/logout')
    @admin_required
    def admin_logout():
        logout_user()
        flash('Admin logged out successfully')
        return redirect(url_for('index'))

    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        # Get statistics
        total_users = User.query.count()
        total_chatbots = Chatbot.query.count()
        trained_chatbots = Chatbot.query.filter_by(is_trained=True).count()
        total_conversations = Conversation.query.count()
        
        # Get recent activity
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        recent_chatbots = Chatbot.query.order_by(Chatbot.created_at.desc()).limit(5).all()
        recent_conversations = Conversation.query.order_by(Conversation.timestamp.desc()).limit(10).all()
        
        # Get database information
        from database_export import get_database_info
        db_info = get_database_info()
        
        return render_template('admin/dashboard.html', 
                             total_users=total_users,
                             total_chatbots=total_chatbots,
                             trained_chatbots=trained_chatbots,
                             total_conversations=total_conversations,
                             recent_users=recent_users,
                             recent_chatbots=recent_chatbots,
                             recent_conversations=recent_conversations,
                             db_info=db_info)

    @app.route('/admin/export-database')
    @admin_required
    def admin_export_database():
        """Export the entire database as SQL statements"""
        try:
            from database_export import export_database_to_sql
            import os
            from flask import send_file, flash
            
            # Export the database
            export_path = export_database_to_sql()
            
            # Check if file was created successfully
            if os.path.exists(export_path):
                flash(f'Database backup created successfully: {os.path.basename(export_path)}')
                
                # Send the file for download
                return send_file(
                    export_path,
                    as_attachment=True,
                    download_name=f'database_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sql',
                    mimetype='application/sql'
                )
            else:
                flash('Failed to create database backup', 'error')
                return redirect(url_for('admin_dashboard'))
                
        except Exception as e:
            flash(f'Error creating database backup: {str(e)}', 'error')
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        page = request.args.get('page', 1, type=int)
        users = User.query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/users.html', users=users, get_user_plan=get_user_plan)

    @app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_user(user_id):
        user = User.query.get_or_404(user_id)
        
        if request.method == 'POST':
            # Update user information
            user.username = request.form['username']
            user.email = request.form['email']
            
            # Handle password update (only if provided)
            new_password = request.form.get('password', '').strip()
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            
            # Handle admin status
            user.is_admin = 'is_admin' in request.form
            
            # Handle plan management
            new_plan_id = request.form.get('plan_id')
            if new_plan_id and new_plan_id != 'current':
                # Get the selected plan
                selected_plan = Plan.query.get(new_plan_id)
                if selected_plan:
                    # Cancel any existing active subscription
                    existing_sub = UserSubscription.query.filter_by(
                        user_id=user.id, 
                        status='active'
                    ).first()
                    if existing_sub:
                        existing_sub.status = 'cancelled'
                    
                    # Create new subscription for the selected plan
                    new_subscription = UserSubscription(
                        user_id=user.id,
                        plan_id=selected_plan.id,
                        status='active',
                        created_at=datetime.utcnow()
                    )
                    db.session.add(new_subscription)
                    flash(f'User plan updated to {selected_plan.name}!')
                else:
                    flash('Invalid plan selected!', 'error')
            elif new_plan_id == 'current':
                # Keep current plan (no change)
                pass
            
            # Check for username/email conflicts
            existing_user = User.query.filter(
                User.username == user.username,
                User.id != user.id
            ).first()
            if existing_user:
                flash('Username already exists!')
                return render_template('admin/edit_user.html', user=user, plans=Plan.query.filter_by(is_active=True).all(), get_user_plan=get_user_plan)
            
            existing_email = User.query.filter(
                User.email == user.email,
                User.id != user.id
            ).first()
            if existing_email:
                flash('Email already exists!')
                return render_template('admin/edit_user.html', user=user, plans=Plan.query.filter_by(is_active=True).all(), get_user_plan=get_user_plan)
            
            db.session.commit()
            flash(f'User {user.username} updated successfully!')
            return redirect(url_for('admin_users'))
        
        # Get all active plans for the dropdown
        plans = Plan.query.filter_by(is_active=True).all()
        return render_template('admin/edit_user.html', user=user, plans=plans, get_user_plan=get_user_plan)

    @app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
    @admin_required
    def admin_toggle_user_admin(user_id):
        user = User.query.get_or_404(user_id)
        
        # Prevent admin from demoting themselves
        if user.id == current_user.id:
            flash('You cannot change your own admin status!')
            return redirect(url_for('admin_users'))
        
        # Toggle admin status
        user.is_admin = not user.is_admin
        db.session.commit()
        
        status = "promoted to admin" if user.is_admin else "demoted from admin"
        flash(f'User {user.username} has been {status}!')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        
        # Prevent admin from deleting themselves
        if user.id == current_user.id:
            flash('You cannot delete your own account!')
            return redirect(url_for('admin_users'))
        
        # Delete user's chatbots and associated data
        for chatbot in user.chatbots:
            # Delete associated files
            for document in chatbot.documents:
                try:
                    delete_document_object(document)
                except Exception as e:
                    print(f"Error deleting file {document.file_path}: {e}")
            
            # Delete chatbot training data
            try:
                chatbot_trainer.delete_chatbot_data(chatbot.id)
            except Exception as e:
                print(f"Error deleting training data: {e}")
            
            # Delete chatbot usage tracking records
            try:
                ChatbotUsage.query.filter_by(chatbot_id=chatbot.id).delete()
            except Exception as e:
                print(f"Error deleting usage tracking for chatbot {chatbot.id}: {e}")

            # This cascade never removed avatars, which merely wasted a little
            # disk before. Object storage is billed per GB, so an orphan here
            # costs money forever.
            delete_avatar(chatbot.avatar_filename)

            purge_training_runs(chatbot.id)
            detach_token_usage(chatbot.id)
        
        db.session.delete(user)
        db.session.commit()
        
        flash(f'User {user.username} and all associated data deleted successfully!')
        return redirect(url_for('admin_users'))

    @app.route('/admin/chatbots')
    @admin_required
    def admin_chatbots():
        page = request.args.get('page', 1, type=int)
        chatbots = Chatbot.query.order_by(Chatbot.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/chatbots.html', chatbots=chatbots)

    @app.route('/admin/chatbots/<int:chatbot_id>/training-data')
    @admin_required
    def admin_chatbot_training_data(chatbot_id):
        """Admin view of chatbot training data JSON"""
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        
        try:
            # Debug: Print the data directory path
            print(f"DEBUG: artifact key: {chatbot_trainer.artifact_key(chatbot_id)}")
            print(f"DEBUG: Looking for training data for chatbot {chatbot_id}")
            
            # Get training data from ChatbotTrainer
            training_data = chatbot_trainer.get_training_data(
                chatbot_id, version=artifact_version(chatbot))
            
            if not training_data:
                # Check if chatbot is marked as trained but no training data exists
                if chatbot.is_trained:
                    trained_when = (chatbot.last_trained_at.strftime('%Y-%m-%d %H:%M UTC')
                                    if chatbot.last_trained_at else 'an unknown date')
                    error_msg = (f"Chatbot '{chatbot.name}' was trained on {trained_when}, but its "
                                 f"training data file is missing from the server. This happens when a "
                                 f"deploy replaces the container without a persistent disk. Retraining "
                                 f"the chatbot will rebuild it.")
                else:
                    error_msg = f"Chatbot '{chatbot.name}' has not been trained yet. Please upload documents and train the chatbot first."
                
                print(f"DEBUG: No training data found for chatbot {chatbot_id}")
                return jsonify({
                    'success': False, 
                    'error': error_msg,
                    'chatbot_name': chatbot.name,
                    'is_trained_in_db': chatbot.is_trained
                }), 404
            
            print(f"DEBUG: Successfully loaded training data for chatbot {chatbot_id}")
            return jsonify({
                'success': True,
                'chatbot_name': chatbot.name,
                'chatbot_id': chatbot_id,
                'training_data': training_data_for_display(
                    training_data, request.args.get('include_vectors') == '1'),
                'is_knowledge_base': chatbot_trainer.is_knowledge_base_format(training_data)
            })
            
        except Exception as e:
            print(f"DEBUG: Error loading training data for chatbot {chatbot_id}: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Error loading training data: {str(e)}',
                'chatbot_name': chatbot.name
            }), 500

    @app.route('/admin/chatbots/<int:chatbot_id>')
    @admin_required
    def admin_chatbot_details(chatbot_id):
        """Admin view of chatbot details - can view any chatbot"""
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
        conversations = Conversation.query.filter_by(chatbot_id=chatbot_id).order_by(Conversation.timestamp.desc()).limit(50).all()
        
        # Get the owner's plan
        owner_plan = get_user_plan(chatbot.owner)
        
        return render_template('admin/chatbot_details.html', 
                             chatbot=chatbot, 
                             documents=documents, 
                             conversations=conversations,
                             owner_plan=owner_plan)

    @app.route('/admin/chatbots/<int:chatbot_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_chatbot(chatbot_id):
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        
        # Delete associated files
        for document in chatbot.documents:
            try:
                delete_document_object(document)
            except Exception as e:
                print(f"Error deleting file {document.file_path}: {e}")
        
        # Delete custom avatar if exists (not predefined)
        delete_avatar(chatbot.avatar_filename)
        
        # Delete chatbot training data
        try:
            chatbot_trainer.delete_chatbot_data(chatbot_id)
        except Exception as e:
            print(f"Error deleting training data: {e}")
        
        # Delete chatbot usage tracking records
        try:
            ChatbotUsage.query.filter_by(chatbot_id=chatbot_id).delete()
        except Exception as e:
            print(f"Error deleting usage tracking: {e}")

        purge_training_runs(chatbot_id)
        detach_token_usage(chatbot_id)
        
        db.session.delete(chatbot)
        db.session.commit()
        
        flash(f'Chatbot {chatbot.name} deleted successfully!')
        return redirect(url_for('admin_chatbots'))

    @app.route('/admin/settings', methods=['GET', 'POST'])
    @admin_required
    def admin_settings():
        if request.method == 'POST':
            section = request.form.get('section')
            print(f"DEBUG: Processing section: {section}")
            print(f"DEBUG: Form fields: {sorted(request.form.keys())}")
            
            if section == 'homepage':
                # Update homepage chatbot settings only
                print("DEBUG: Processing homepage section")
                homepage_chatbot_id = request.form.get('homepage_chatbot_id')
                homepage_chatbot_title = request.form.get('homepage_chatbot_title', 'Platform Assistant')
                homepage_chatbot_placeholder = request.form.get('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                
                print(f"DEBUG: Homepage values - ID: {homepage_chatbot_id}, Title: {homepage_chatbot_title}, Placeholder: {homepage_chatbot_placeholder}")
                
                set_setting('homepage_chatbot_id', homepage_chatbot_id)
                set_setting('homepage_chatbot_title', homepage_chatbot_title)
                set_setting('homepage_chatbot_placeholder', homepage_chatbot_placeholder)
                
                flash('Homepage settings updated successfully!')
                
            elif section == 'contact':
                # Update contact page settings only
                print("DEBUG: Processing contact section")
                contact_email = request.form.get('contact_email', 'support@owlbee.ai')
                contact_response_time = request.form.get('contact_response_time', 'We typically respond within 24 hours')
                contact_support_hours = request.form.get('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
                contact_live_chat_text = request.form.get('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
                
                print(f"DEBUG: Contact values - Email: {contact_email}, Response Time: {contact_response_time}")
                
                set_setting('contact_email', contact_email)
                set_setting('contact_response_time', contact_response_time)
                set_setting('contact_support_hours', contact_support_hours)
                set_setting('contact_live_chat_text', contact_live_chat_text)
                
                flash('Contact page settings updated successfully!')
                
            elif section == 'openai':
                # Update the default model tier only
                print("DEBUG: Processing openai section")
                # normalize_alias keeps a forged or stale value from reaching the API
                openai_model = model_catalog.normalize_alias(request.form.get('openai_model'))
                print(f"DEBUG: Default model tier: {openai_model}")
                set_setting('openai_model', openai_model)
                
                flash('Default AI model updated successfully!')

            elif section == 'token_limit':
                # Message shown to a visitor when the bot's owner is over their cap
                message = request.form.get('token_limit_message', '').strip()
                set_setting('token_limit_message', message or DEFAULT_TOKEN_LIMIT_MESSAGE)
                flash('Monthly limit message updated successfully!')
                
            elif section == 'stripe':
                # Update Stripe settings only
                print("DEBUG: Processing stripe section")
                stripe_publishable_key = request.form.get('stripe_publishable_key', '').strip()
                stripe_secret_key = request.form.get('stripe_secret_key', '').strip()
                stripe_webhook_secret = request.form.get('stripe_webhook_secret', '').strip()
                
                set_setting('stripe_publishable_key', stripe_publishable_key)
                update_secret_setting_from_form('stripe_secret_key', stripe_secret_key,
                                                request.form.get('clear_stripe_secret_key'))
                update_secret_setting_from_form('stripe_webhook_secret', stripe_webhook_secret,
                                                request.form.get('clear_stripe_webhook_secret'))
                
                flash('Stripe settings updated successfully!')
            else:
                print(f"DEBUG: Unknown section: {section}")
                flash('Unknown section. No settings updated.')
            
            return redirect(url_for('admin_settings'))
        
        # Get current homepage settings
        current_chatbot_id = get_setting('homepage_chatbot_id')
        current_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        current_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get current contact page settings
        current_contact_email = get_setting('contact_email', 'support@owlbee.ai')
        current_contact_response_time = get_setting('contact_response_time', 'We typically respond within 24 hours')
        current_contact_support_hours = get_setting('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
        current_contact_live_chat_text = get_setting('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
        
        # Get current Stripe settings
        current_stripe_publishable_key = get_setting('stripe_publishable_key', '')
        # Write-only fields: the template only needs to know whether a value exists.
        # get_setting (not get_secret_setting) on purpose - the plaintext is never loaded here.
        stripe_secret_key_configured = bool(get_setting('stripe_secret_key', ''))
        stripe_webhook_secret_configured = bool(get_setting('stripe_webhook_secret', ''))
        
        # Get the current default model tier (stored as an alias)
        current_openai_model = model_catalog.normalize_alias(get_setting('openai_model'))
        model_profiles = model_catalog.selectable_profiles()
        current_token_limit_message = get_setting('token_limit_message', DEFAULT_TOKEN_LIMIT_MESSAGE)
        
        # Get current training prompt
        current_training_prompt = get_setting('training_prompt', '')
        
        # Get all trained chatbots for selection
        trained_chatbots = Chatbot.query.filter_by(is_trained=True).all()
        
        # Get current chatbot object if configured
        current_chatbot = None
        if current_chatbot_id:
            current_chatbot = Chatbot.query.get(current_chatbot_id)
        
        return render_template('admin/settings.html',
                             current_chatbot_id=current_chatbot_id,
                             current_chatbot=current_chatbot,
                             current_title=current_title,
                             current_placeholder=current_placeholder,
                             current_contact_email=current_contact_email,
                             current_contact_response_time=current_contact_response_time,
                             current_contact_support_hours=current_contact_support_hours,
                             current_contact_live_chat_text=current_contact_live_chat_text,
                             current_stripe_publishable_key=current_stripe_publishable_key,
                             stripe_secret_key_configured=stripe_secret_key_configured,
                             stripe_webhook_secret_configured=stripe_webhook_secret_configured,
                             current_openai_model=current_openai_model,
                             model_profiles=model_profiles,
                             current_token_limit_message=current_token_limit_message,
                             current_training_prompt=current_training_prompt,
                             trained_chatbots=trained_chatbots)

    @app.route('/admin/settings/homepage', methods=['POST'])
    @admin_required
    def admin_settings_homepage():
        """AJAX endpoint for homepage settings"""
        try:
            homepage_chatbot_id = request.form.get('homepage_chatbot_id')
            homepage_chatbot_title = request.form.get('homepage_chatbot_title', 'Platform Assistant')
            homepage_chatbot_placeholder = request.form.get('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
            
            set_setting('homepage_chatbot_id', homepage_chatbot_id)
            set_setting('homepage_chatbot_title', homepage_chatbot_title)
            set_setting('homepage_chatbot_placeholder', homepage_chatbot_placeholder)
            
            return {'success': True, 'message': 'Homepage settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating homepage settings: {str(e)}'}, 500

    @app.route('/admin/settings/contact', methods=['POST'])
    @admin_required
    def admin_settings_contact():
        """AJAX endpoint for contact settings"""
        try:
            contact_email = request.form.get('contact_email', 'support@owlbee.ai')
            contact_response_time = request.form.get('contact_response_time', 'We typically respond within 24 hours')
            contact_support_hours = request.form.get('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
            contact_live_chat_text = request.form.get('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
            
            set_setting('contact_email', contact_email)
            set_setting('contact_response_time', contact_response_time)
            set_setting('contact_support_hours', contact_support_hours)
            set_setting('contact_live_chat_text', contact_live_chat_text)
            
            return {'success': True, 'message': 'Contact settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating contact settings: {str(e)}'}, 500

    @app.route('/admin/settings/openai', methods=['POST'])
    @admin_required
    def admin_settings_openai():
        """AJAX endpoint for the default model tier"""
        try:
            # normalize_alias keeps a forged or stale value from reaching the API
            openai_model = model_catalog.normalize_alias(request.form.get('openai_model'))
            set_setting('openai_model', openai_model)
            profile = model_catalog.get_profile(openai_model)
            return {'success': True,
                    'message': f'Default AI model set to {profile.display_name}.'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating OpenAI settings: {str(e)}'}, 500

    @app.route('/admin/settings/token-limit', methods=['POST'])
    @admin_required
    def admin_settings_token_limit():
        """AJAX endpoint for the monthly-limit message shown to chat visitors"""
        try:
            message = request.form.get('token_limit_message', '').strip()
            set_setting('token_limit_message', message or DEFAULT_TOKEN_LIMIT_MESSAGE)
            return {'success': True, 'message': 'Monthly limit message updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating limit message: {str(e)}'}, 500

    @app.route('/admin/settings/stripe', methods=['POST'])
    @admin_required
    def admin_settings_stripe():
        """AJAX endpoint for Stripe settings"""
        try:
            stripe_publishable_key = request.form.get('stripe_publishable_key', '').strip()
            stripe_secret_key = request.form.get('stripe_secret_key', '').strip()
            stripe_webhook_secret = request.form.get('stripe_webhook_secret', '').strip()
            
            set_setting('stripe_publishable_key', stripe_publishable_key)
            update_secret_setting_from_form('stripe_secret_key', stripe_secret_key,
                                            request.form.get('clear_stripe_secret_key'))
            update_secret_setting_from_form('stripe_webhook_secret', stripe_webhook_secret,
                                            request.form.get('clear_stripe_webhook_secret'))
            
            return {'success': True, 'message': 'Stripe settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating Stripe settings: {str(e)}'}, 500

    @app.route('/admin/settings/training-prompt', methods=['POST'])
    @admin_required
    def admin_settings_training_prompt():
        """AJAX endpoint for training prompt settings"""
        try:
            training_prompt = request.form.get('training_prompt', '').strip()
            
            if not training_prompt:
                return {'success': False, 'message': 'Training prompt cannot be empty'}, 400
            
            set_setting('training_prompt', training_prompt)
            
            return {'success': True, 'message': 'Training prompt updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating training prompt: {str(e)}'}, 500

    def allowed_file(filename):
        ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'json', 'xlsx'}
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def create_demo_chatbot_internal():
        """Create a demo chatbot for the homepage if it doesn't exist"""
        demo_embed_code = 'a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb'
        
        # Check if demo chatbot already exists
        existing_chatbot = Chatbot.query.filter_by(embed_code=demo_embed_code).first()
        if existing_chatbot and existing_chatbot.is_trained:
            print(f"[OK] Demo chatbot already exists and is trained: {demo_embed_code}")
            return existing_chatbot
        
        # Create demo user if doesn't exist
        demo_user = User.query.filter_by(username='demo').first()
        if not demo_user:
            demo_user = User(
                username='demo',
                email='demo@chatbot-platform.com',
                password_hash=generate_password_hash('demo123')
            )
            db.session.add(demo_user)
            db.session.commit()
        
        # Create or update demo chatbot
        if existing_chatbot:
            demo_chatbot = existing_chatbot
            # Update system prompt if it's the default
            if not demo_chatbot.system_prompt or demo_chatbot.system_prompt == "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.":
                demo_chatbot.system_prompt = "You are the Platform Assistant for the ChatBot Platform. You are knowledgeable, friendly, and enthusiastic about helping users understand how to create and deploy AI chatbots. You help users with questions about features, setup, training, and deployment. Be encouraging and provide clear, actionable guidance."
                db.session.commit()
        else:
            demo_chatbot = Chatbot(
                name='Platform Assistant',
                description='A helpful assistant that can answer questions about the chatbot platform',
                system_prompt='You are the Platform Assistant for the ChatBot Platform. You are knowledgeable, friendly, and enthusiastic about helping users understand how to create and deploy AI chatbots. You help users with questions about features, setup, training, and deployment. Be encouraging and provide clear, actionable guidance.',
                embed_code=demo_embed_code,
                user_id=demo_user.id,
                is_trained=False
            )
            db.session.add(demo_chatbot)
            db.session.commit()
        
        # Create demo training data
        demo_content = """
About the Chatbot Platform

This is a comprehensive AI-powered chatbot platform that enables businesses and individuals to create intelligent conversational assistants for their websites. Our platform combines ease of use with powerful AI technology to deliver professional chatbot solutions.

Core Services Offered

Document-Based Training: Upload PDF, DOCX, and TXT files to train your chatbot with your specific content. The platform extracts text from documents and creates intelligent responses based on your material.

Multi-Bot Management: Create unlimited chatbots for different purposes - customer support, FAQ assistance, product information, or specialized knowledge bases.

Easy Website Integration: Get a simple embed code that can be added to any website in minutes. No technical expertise required.

AI-Powered Responses: Uses advanced natural language processing with fallback to OpenAI integration for enhanced conversational abilities.

Real-Time Chat Interface: Professional chat widget with typing indicators, customizable themes, and mobile-responsive design.

Conversation Analytics: Track all conversations, monitor chatbot performance, and analyze user interactions through your dashboard.

How to Get Started

Step 1: Create Your Account
Register for a free account using your email address. No credit card required to start building chatbots.

Step 2: Create Your First Chatbot
From your dashboard, click "Create Chatbot" and give it a name and description that reflects its purpose.

Step 3: Upload Training Documents
Upload relevant documents (manuals, FAQs, product information, policies) in PDF, DOCX, TXT, or JSON format. The platform will process these automatically.

Step 4: Train Your Chatbot
Click the "Train" button to process your documents and create the AI knowledge base. This usually takes just a few minutes.

Step 5: Get Your Embed Code
Once trained, copy the provided embed code and paste it into your website's HTML. The chatbot will appear as a floating widget.

Usage Examples

Customer Support: Upload your support documentation, product manuals, and FAQ documents to create a 24/7 customer service assistant.

Educational Content: Teachers can upload course materials, syllabi, and reading lists to create study assistants for students.

Business Information: Real estate agents can upload property details, market reports, and service information to help potential clients.

Technical Documentation: Software companies can upload API documentation, user guides, and troubleshooting materials.

Company Policies: HR departments can create chatbots trained on employee handbooks, benefits information, and company policies.

Platform Features

Drag-and-Drop File Upload: Simple interface for uploading multiple documents at once.

Automatic Text Extraction: Intelligent processing of PDF and DOCX files to extract relevant text content.

Smart Response Generation: AI algorithms that understand context and provide relevant answers from your training materials.

Conversation History: Complete logs of all chatbot interactions for analysis and improvement.

Multiple Deployment Options: Embed codes work on WordPress, Shopify, custom websites, and any HTML-based platform.

Mobile Optimization: Chatbot widgets automatically adapt to mobile devices for seamless user experience.

Customization Options: Adjust colors, positioning, welcome messages, and placeholder text to match your brand.

Technical Specifications

Supported File Formats: PDF (including scanned documents with OCR), Microsoft Word DOCX, and plain text TXT files.

File Size Limits: Up to 16MB per file upload with support for multiple files per chatbot.

Response Time: Typically under 2 seconds for generating responses from trained content.

Deployment: Cloud-hosted solution with 99.9% uptime and automatic scaling.

Security: All data is encrypted in transit and at rest, with secure API endpoints for chat functionality.

Integration: RESTful API available for custom integrations and advanced use cases.

Pricing and Plans

Free Tier: Create unlimited chatbots, upload documents, and embed on websites at no cost.

OpenAI Integration: Optional upgrade for enhanced AI responses using GPT technology (requires OpenAI API key).

Enterprise Features: Contact us for advanced analytics, custom branding, and priority support options.

Support and Resources

Documentation: Comprehensive guides available for setup, customization, and troubleshooting.

Community: Access to user forums and knowledge sharing with other platform users.

Contact Support: Direct support available through the contact form for technical assistance.

Regular Updates: Platform continuously improved with new features and AI enhancements.

Getting Help

If you need assistance, you can:
- Check the documentation and guides in your dashboard
- Contact support through the contact form
- Register for an account to access the full tutorial system
- Use this demo chatbot to ask specific questions about features and functionality

The platform is designed to be user-friendly while providing powerful AI capabilities for creating professional chatbot solutions.
"""
        
        try:
            # Train demo chatbot with knowledge base generation
            demo_chatbot_info = {
                'name': demo_chatbot.name,
                'description': demo_chatbot.description or ''
            }
            # Runs inline (not through the background runner): this happens at
            # boot, before any request, and the demo bot is ours - a failure here
            # must never keep the app from starting.
            chatbot_trainer.train_chatbot(
                demo_chatbot.id, [('platform_guide.txt', demo_content)],
                chatbot_info=demo_chatbot_info,
                model_alias=model_catalog.DEFAULT_ALIAS)
            demo_chatbot.is_trained = True
            demo_chatbot.last_trained_at = datetime.utcnow()
            db.session.commit()
            print(f"[OK] Demo chatbot created and trained with embed code: {demo_embed_code}")
        except Exception as e:
            print(f"[WARNING] Demo chatbot created but training failed: {e}")
            import traceback
            traceback.print_exc()
        
        return demo_chatbot

    def read_plan_model_fields():
        """Parse the model-tier and token-allowance fields off a plan form.

        filter_allowed() drops anything not in the catalog, so a forged POST
        cannot inject an arbitrary string into the column. An empty or absent
        token limit is stored as NULL, which means unlimited.
        """
        allowed = model_catalog.filter_allowed(request.form.getlist('allowed_models'))

        if 'unlimited_tokens' in request.form:
            token_limit = None
        else:
            raw = (request.form.get('monthly_token_limit') or '').strip().replace(',', '')
            try:
                token_limit = int(raw) if raw else None
            except ValueError:
                token_limit = None
            if token_limit is not None and token_limit <= 0:
                token_limit = None

        return {
            'allowed_models': json.dumps(allowed),
            'monthly_token_limit': token_limit,
            'web_search_enabled': 'web_search_enabled' in request.form,
        }

    @app.route('/admin/usage')
    @admin_required
    def admin_usage():
        """Token spend for every user in a given month."""
        period = request.args.get('period') or current_period_key()

        rows = []
        for user in User.query.order_by(User.username).all():
            summary = get_usage_summary(user, period)
            if summary['used'] or summary['blocked_count']:
                rows.append({'user': user, 'summary': summary})
        rows.sort(key=lambda r: r['summary']['used'], reverse=True)

        # Months that actually have data, newest first, for the period picker
        periods = [p[0] for p in db.session.query(TokenUsage.period_key)
                   .distinct().order_by(TokenUsage.period_key.desc()).all()]
        if period not in periods:
            periods.insert(0, period)

        return render_template('admin/usage.html', rows=rows, period=period,
                               periods=periods,
                               total_tokens=sum(r['summary']['used'] for r in rows))

    @app.route('/admin/users/<int:user_id>/reset-usage', methods=['POST'])
    @admin_required
    def admin_reset_usage(user_id):
        """Zero one user's current-month usage.

        Usage resets on its own each month - rows are keyed by 'YYYY-MM', so a
        new month simply starts at zero with no scheduled job to fail. This is
        the support escape hatch for when someone was blocked by mistake.
        """
        user = User.query.get_or_404(user_id)
        period = current_period_key()
        try:
            deleted = TokenUsage.query.filter_by(user_id=user_id, period_key=period).delete()
            db.session.commit()
            flash(f'Reset {period} token usage for {user.username} ({deleted} record(s)).')
        except Exception as e:
            db.session.rollback()
            flash(f'Could not reset usage for {user.username}: {e}', 'error')
        return redirect(request.referrer or url_for('admin_usage'))

    @app.route('/admin/plans')
    @admin_required
    def admin_plans():
        page = request.args.get('page', 1, type=int)
        plans = Plan.query.order_by(Plan.monthly_price.asc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/plans.html', plans=plans,
                               model_profiles=model_catalog.selectable_profiles())

    @app.route('/admin/plans/create', methods=['GET', 'POST'])
    @admin_required
    def admin_create_plan():
        if request.method == 'POST':
            name = request.form['name']
            description = request.form['description']
            monthly_price = float(request.form['monthly_price'])
            yearly_price = float(request.form['yearly_price'])
            chatbot_limit = int(request.form['chatbot_limit'])
            file_size_limit_mb = int(request.form['file_size_limit_mb'])
            stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            is_active = 'is_active' in request.form
            show_contact_sales = 'show_contact_sales' in request.form
            
            # Convert features text to JSON
            features_list = [feature.strip() for feature in features_text.split('\n') if feature.strip()]
            features_json = json.dumps(features_list)
            
            model_fields = read_plan_model_fields()
            
            plan = Plan(
                name=name,
                description=description,
                monthly_price=monthly_price,
                yearly_price=yearly_price,
                chatbot_limit=chatbot_limit,
                file_size_limit_mb=file_size_limit_mb,
                stripe_monthly_price_id=stripe_monthly_price_id if stripe_monthly_price_id else None,
                stripe_yearly_price_id=stripe_yearly_price_id if stripe_yearly_price_id else None,
                features=features_json,
                is_active=is_active,
                show_contact_sales=show_contact_sales,
                allowed_models=model_fields['allowed_models'],
                monthly_token_limit=model_fields['monthly_token_limit'],
                web_search_enabled=model_fields['web_search_enabled']
            )
            
            db.session.add(plan)
            db.session.commit()
            
            flash(f'Plan "{name}" created successfully!')
            return redirect(url_for('admin_plans'))
        
        return render_template('admin/create_plan.html',
                               model_profiles=model_catalog.selectable_profiles(),
                               default_allowed_models=[model_catalog.CHEAPEST_ALIAS])

    @app.route('/admin/plans/<int:plan_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_plan(plan_id):
        plan = Plan.query.get_or_404(plan_id)
        
        if request.method == 'POST':
            plan.name = request.form['name']
            plan.description = request.form['description']
            plan.monthly_price = float(request.form['monthly_price'])
            plan.yearly_price = float(request.form['yearly_price'])
            plan.chatbot_limit = int(request.form['chatbot_limit'])
            plan.file_size_limit_mb = int(request.form['file_size_limit_mb'])
            plan.stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            plan.stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            plan.is_active = 'is_active' in request.form
            plan.show_contact_sales = 'show_contact_sales' in request.form
            
            # Convert features text to JSON
            features_list = [feature.strip() for feature in features_text.split('\n') if feature.strip()]
            plan.features = json.dumps(features_list)
            
            model_fields = read_plan_model_fields()
            plan.allowed_models = model_fields['allowed_models']
            plan.monthly_token_limit = model_fields['monthly_token_limit']
            plan.web_search_enabled = model_fields['web_search_enabled']
            
            # Check for name conflicts
            existing_plan = Plan.query.filter(
                Plan.name == plan.name,
                Plan.id != plan.id
            ).first()
            if existing_plan:
                flash('Plan name already exists!')
                return render_template('admin/edit_plan.html', plan=plan,
                                       model_profiles=model_catalog.selectable_profiles(),
                                       plan_allowed_models=get_allowed_models(plan))
            
            db.session.commit()
            flash(f'Plan "{plan.name}" updated successfully!')
            return redirect(url_for('admin_plans'))
        
        return render_template('admin/edit_plan.html', plan=plan,
                               model_profiles=model_catalog.selectable_profiles(),
                               plan_allowed_models=get_allowed_models(plan))

    @app.route('/admin/plans/<int:plan_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_plan(plan_id):
        plan = Plan.query.get_or_404(plan_id)
        
        db.session.delete(plan)
        db.session.commit()
        
        flash(f'Plan "{plan.name}" deleted successfully!')
        return redirect(url_for('admin_plans'))

    @app.route('/admin/resend-settings/test', methods=['POST'])
    @admin_required
    def admin_test_resend():
        try:
            # Send test email using Resend
            test_subject = "Resend Test Email"
            test_body = f"""
This is a test email from your Chatbot Platform using Resend.

Resend Configuration:
- From: {os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')} <{os.getenv('RESEND_FROM_EMAIL')}>
- To: {os.getenv('RESEND_ADMIN_EMAIL')}

If you receive this email, your Resend configuration is working correctly!

Sent at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
            """
            
            admin_email = os.getenv('RESEND_ADMIN_EMAIL')
            if not admin_email:
                return jsonify({'success': False, 'message': 'RESEND_ADMIN_EMAIL not configured'})
            
            send_email(admin_email, test_subject, test_body)
            return jsonify({'success': True, 'message': 'Test email sent successfully!'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to send test email: {str(e)}'})

    @app.route('/admin/site-settings', methods=['GET', 'POST'])
    @admin_required
    def admin_site_settings():
        if request.method == 'POST':
            site_title = request.form['site_title']
            meta_tags = request.form.get('meta_tags', '').strip()
            hero_title = request.form.get('hero_title', '').strip()
            hero_subtitle = request.form.get('hero_subtitle', '').strip()
            
            # Handle logo upload - convert to base64
            logo_file = request.files.get('logo')
            logo_base64 = None
            
            # Handle hero icon upload - convert to base64
            hero_icon_file = request.files.get('hero_icon')
            hero_icon_base64 = None
            
            if logo_file and logo_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in logo_file.filename and \
                   logo_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    logo_base64 = encode_image_to_base64(logo_file)
            
            if hero_icon_file and hero_icon_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in hero_icon_file.filename and \
                   hero_icon_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    hero_icon_base64 = encode_image_to_base64(hero_icon_file)
            
            # Get or create site settings
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if not site_settings:
                site_settings = SiteSettings()
                db.session.add(site_settings)
            
            # Update settings
            site_settings.site_title = site_title
            site_settings.meta_tags = meta_tags
            site_settings.hero_title = hero_title
            site_settings.hero_subtitle = hero_subtitle
            
            if logo_base64:
                # Store base64 logo and clear old filename
                site_settings.logo_base64 = logo_base64
                site_settings.logo_filename = None  # Clear old filename
            
            if hero_icon_base64:
                # Store base64 hero icon and clear old filename
                site_settings.hero_icon_base64 = hero_icon_base64
                site_settings.hero_icon_filename = None  # Clear old filename
            
            db.session.commit()
            
            flash('Site settings updated successfully!')
            return redirect(url_for('admin_site_settings'))
        
        site_settings = get_site_settings()
        return render_template('admin/site_settings.html', site_settings=site_settings)

    @app.route('/admin/site-settings/delete-logo', methods=['POST'])
    @admin_required
    def admin_delete_logo():
        try:
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if site_settings and (site_settings.logo_filename or site_settings.logo_base64):
                # Clear both filename and base64 data
                site_settings.logo_filename = None
                site_settings.logo_base64 = None
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Logo deleted successfully!'})
            else:
                return jsonify({'success': False, 'message': 'No logo to delete'})
                
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to delete logo: {str(e)}'})

    @app.route('/admin/site-settings/delete-hero-icon', methods=['POST'])
    @admin_required
    def admin_delete_hero_icon():
        try:
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if site_settings and (site_settings.hero_icon_filename or site_settings.hero_icon_base64):
                # Clear both filename and base64 data
                site_settings.hero_icon_filename = None
                site_settings.hero_icon_base64 = None
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Hero icon deleted successfully!'})
            else:
                return jsonify({'success': False, 'message': 'No hero icon to delete'})
                
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to delete hero icon: {str(e)}'})

    # FAQ Management Routes
    @app.route('/admin/faq', methods=['GET', 'POST'])
    @admin_required
    def admin_faq():
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add':
                question = request.form.get('question', '').strip()
                answer = request.form.get('answer', '').strip()
                order = request.form.get('order', 0, type=int)
                
                if question and answer:
                    # Get the next order number if not specified
                    if order == 0:
                        max_order = db.session.query(db.func.max(FAQ.order)).scalar() or 0
                        order = max_order + 1
                    
                    faq = FAQ(question=question, answer=answer, order=order)
                    db.session.add(faq)
                    db.session.commit()
                    flash('FAQ question added successfully!')
                else:
                    flash('Both question and answer are required.', 'error')
            
            elif action == 'edit':
                faq_id = request.form.get('faq_id', type=int)
                question = request.form.get('question', '').strip()
                answer = request.form.get('answer', '').strip()
                order = request.form.get('order', 0, type=int)
                
                if faq_id and question and answer:
                    faq = FAQ.query.get_or_404(faq_id)
                    faq.question = question
                    faq.answer = answer
                    faq.order = order
                    faq.updated_at = datetime.utcnow()
                    db.session.commit()
                    flash('FAQ question updated successfully!')
                else:
                    flash('Invalid data provided.', 'error')
            
            elif action == 'delete':
                faq_id = request.form.get('faq_id', type=int)
                if faq_id:
                    faq = FAQ.query.get_or_404(faq_id)
                    db.session.delete(faq)
                    db.session.commit()
                    flash('FAQ question deleted successfully!')
                else:
                    flash('Invalid FAQ ID.', 'error')
            
            elif action == 'toggle':
                faq_id = request.form.get('faq_id', type=int)
                if faq_id:
                    faq = FAQ.query.get_or_404(faq_id)
                    faq.is_active = not faq.is_active
                    faq.updated_at = datetime.utcnow()
                    db.session.commit()
                    status = 'activated' if faq.is_active else 'deactivated'
                    flash(f'FAQ question {status} successfully!')
                else:
                    flash('Invalid FAQ ID.', 'error')
            
            return redirect(url_for('admin_faq'))
        
        # Get all FAQ items ordered by order field
        faqs = FAQ.query.order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
        return render_template('admin/faq.html', faqs=faqs)

    @app.route('/admin/faq/<int:faq_id>/edit', methods=['GET'])
    @admin_required
    def admin_faq_edit(faq_id):
        faq = FAQ.query.get_or_404(faq_id)
        return render_template('admin/faq_edit.html', faq=faq)

    @app.route('/admin/faq/<int:faq_id>/delete', methods=['POST'])
    @admin_required
    def admin_faq_delete(faq_id):
        faq = FAQ.query.get_or_404(faq_id)
        db.session.delete(faq)
        db.session.commit()
        flash('FAQ question deleted successfully!')
        return redirect(url_for('admin_faq'))

    # Homepage Section Management Routes
    @app.route('/admin/homepage-sections', methods=['GET', 'POST'])
    @admin_required
    def admin_homepage_sections():
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'update':
                section_id = request.form.get('section_id', type=int)
                title = request.form.get('title', '').strip()
                subtitle = request.form.get('subtitle', '').strip()
                content = request.form.get('content', '').strip()
                
                if section_id:
                    section = HomepageSection.query.get_or_404(section_id)
                    section.title = title
                    section.subtitle = subtitle
                    section.content = content
                    section.updated_at = datetime.utcnow()
                    db.session.commit()
                    flash('Homepage section updated successfully!')
                else:
                    flash('Invalid section ID.', 'error')
            
            elif action == 'toggle':
                section_id = request.form.get('section_id', type=int)
                if section_id:
                    section = HomepageSection.query.get_or_404(section_id)
                    section.is_active = not section.is_active
                    section.updated_at = datetime.utcnow()
                    db.session.commit()
                    status = 'activated' if section.is_active else 'deactivated'
                    flash(f'Homepage section {status} successfully!')
                else:
                    flash('Invalid section ID.', 'error')
            
            return redirect(url_for('admin_homepage_sections'))
        
        # Get all homepage sections ordered by order field
        sections = HomepageSection.query.order_by(HomepageSection.order.asc(), HomepageSection.created_at.asc()).all()
        return render_template('admin/homepage_sections.html', sections=sections)

    @app.route('/admin/homepage-sections/<int:section_id>/edit', methods=['GET'])
    @admin_required
    def admin_homepage_section_edit(section_id):
        section = HomepageSection.query.get_or_404(section_id)
        return render_template('admin/homepage_section_edit.html', section=section)

    @app.context_processor
    def inject_site_settings():
        """Make site settings available in all templates"""
        return dict(site_settings=get_site_settings())

    # Helper injection removed to avoid initialization order issues

    # -----------------------------
    # Payments (Stripe) - Guarded
    # -----------------------------
    def get_stripe_config():
        publishable_key = get_setting('stripe_publishable_key', '')
        secret_key = get_secret_setting('stripe_secret_key', '')
        webhook_secret = get_secret_setting('stripe_webhook_secret', '')
        return publishable_key, secret_key, webhook_secret

    def is_stripe_ready():
        if stripe is None:
            return False
        _, secret_key, _ = get_stripe_config()
        return bool(secret_key)

    @app.route('/create-checkout-session', methods=['POST'])
    def create_checkout_session():
        try:
            # Basic guardrails
            if not is_stripe_ready():
                return jsonify({'error': 'Payments not configured'}), 503

            data = request.get_json(silent=True) or {}
            plan_id = data.get('plan_id')
            billing_cycle = (data.get('billing_cycle') or 'monthly').lower()

            if not plan_id or billing_cycle not in {'monthly', 'yearly'}:
                return jsonify({'error': 'Invalid request'}), 400

            plan = Plan.query.get(plan_id)
            if not plan or not plan.is_active:
                return jsonify({'error': 'Plan not found'}), 404

            # Choose price ID by cycle
            price_id = plan.stripe_monthly_price_id if billing_cycle == 'monthly' else plan.stripe_yearly_price_id
            if not price_id:
                return jsonify({'error': 'Price ID not configured for this plan'}), 400

            # Configure stripe
            _, secret_key, _ = get_stripe_config()
            stripe.api_key = secret_key

            # Build success/cancel URLs
            success_url = url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
            cancel_url = url_for('plans', _external=True)

            # Create checkout session (subscription)
            session_args = {
                'mode': 'subscription',
                'payment_method_types': ['card'],
                'line_items': [{'price': price_id, 'quantity': 1}],
                'success_url': success_url,
                'cancel_url': cancel_url,
                'metadata': {
                    'plan_id': str(plan.id),
                    'plan_name': plan.name,
                    'billing_cycle': billing_cycle,
                },
            }
            # Pass customer_email if logged in
            if current_user.is_authenticated:
                session_args['customer_email'] = current_user.email  # type: ignore[attr-defined]

            checkout_session = stripe.checkout.Session.create(**session_args)
            return jsonify({'checkout_url': checkout_session.url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/payment-success')
    @login_required
    def payment_success():
        # Verify session and upsert subscription, then redirect back to plans
        try:
            if not is_stripe_ready():
                flash('Payment processed, but Stripe is not fully configured.', 'warning')
                return redirect(url_for('plans'))

            session_id = request.args.get('session_id')
            if not session_id:
                return redirect(url_for('plans'))

            _, secret_key, _ = get_stripe_config()
            stripe.api_key = secret_key

            checkout_session = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
            if not checkout_session:
                return redirect(url_for('plans'))

            # Read plan metadata we set when creating the session
            meta = checkout_session.get('metadata') or {}
            plan_id_str = meta.get('plan_id')
            if plan_id_str and plan_id_str.isdigit():
                plan_id = int(plan_id_str)
                plan = Plan.query.get(plan_id)
                if plan:
                    # Extract Stripe subscription data
                    sub_id = None
                    current_period_end = None
                    sub_obj = checkout_session.get('subscription')
                    if isinstance(sub_obj, dict):
                        sub_id = sub_obj.get('id')
                        ts = sub_obj.get('current_period_end')
                        if ts:
                            try:
                                from datetime import datetime
                                current_period_end = datetime.utcfromtimestamp(int(ts))
                            except Exception:
                                current_period_end = None
                    elif isinstance(sub_obj, str):
                        sub_id = sub_obj

                    # Ensure table exists and clean transaction state
                    try:
                        from sqlalchemy import inspect
                        insp = inspect(db.engine)
                        if not insp.has_table('user_subscription'):
                            db.create_all()
                    except Exception:
                        # Ignore table introspection errors; create_all later if needed
                        pass

                    # Retryable write
                    for attempt in range(2):
                        try:
                            # Clear any failed transaction state
                            try:
                                db.session.rollback()
                            except Exception:
                                pass

                            # Deactivate previous subs via ORM to avoid bulk-update transaction issues
                            prev_subs = UserSubscription.query.filter_by(user_id=current_user.id, status='active').all()
                            for ps in prev_subs:
                                ps.status = 'canceled'

                            new_sub = UserSubscription(
                                user_id=current_user.id,
                                plan_id=plan.id,
                                stripe_subscription_id=sub_id,
                                status='active',
                                current_period_end=current_period_end
                            )
                            db.session.add(new_sub)
                            db.session.commit()
                            break
                        except Exception:
                            db.session.rollback()
                            # Try to create tables and retry once
                            try:
                                db.create_all()
                            except Exception:
                                pass
                            if attempt == 1:
                                raise

            flash('Subscription activated successfully.', 'success')
        except Exception as e:
            flash(f'Payment processed but could not update subscription: {e}', 'warning')
        return redirect(url_for('plans'))

    @app.route('/stripe-webhook', methods=['POST'])
    def stripe_webhook():
        # Gracefully no-op if not configured
        if not is_stripe_ready():
            return ('', 200)

        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature', '')
        _, _, webhook_secret = get_stripe_config()

        # If no webhook secret, accept without processing to avoid outages
        if not webhook_secret:
            return ('', 200)

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception:
            return ('', 400)

        # Handle a few key events (logging only for now)
        et = event['type']
        obj = event['data']['object']
        if et == 'checkout.session.completed':
            # Subscription created/paid
            pass
        elif et == 'invoice.payment_succeeded':
            pass
        elif et == 'customer.subscription.deleted':
            pass
        # Extend later with DB updates when subscription model is added

        return ('', 200)

    @app.route('/favicon.ico')
    def favicon():
        """Serve favicon.ico file"""
        try:
            favicon_path = os.path.join(app.static_folder, 'favicon.ico')
            if os.path.exists(favicon_path):
                return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
            else:
                # Return 204 No Content if favicon doesn't exist yet
                return ('', 204)
        except Exception:
            # Return 204 No Content on any error to prevent deployment failures
            return ('', 204)

    @app.errorhandler(500)
    def handle_500_error(e):
        """Handle 500 errors specifically for database rollback issues"""
        # Check if it's a database session rollback error
        if 'PendingRollbackError' in str(type(e)) or 'PendingRollbackError' in str(e):
            db.session.rollback()
            flash('A database error occurred. Please try again.', 'error')
            return redirect(url_for('index'))
        
        # For other 500 errors, let Flask handle them normally
        raise e

    with app.app_context():
        db.create_all()
        # Say plainly, in the logs, where files are going.
        try:
            log_storage_status()
            audit_missing_training_data()
        except Exception as e:
            print(f"[WARNING] Storage check failed: {e}")
        # A daemon thread does not survive a restart, so any run this process id
        # owned is dead by definition. Without this, rows sit at 'running'
        # forever and a polling browser never stops.
        try:
            reaped = training_runner.reap_stale_runs(boot=True)
            if reaped:
                print(f"Marked {reaped} interrupted training run(s) as orphaned")
        except Exception as e:
            print(f"[WARNING] Stale training-run reaper failed at boot: {e}")
        # Create demo chatbot after all services are initialized
        try:
            create_demo_chatbot_internal()
        except Exception as e:
            print(f"[WARNING] Failed to create demo chatbot: {e}")
    
    return app 