"""Single source of truth for the Owlbee model tiers.

Users see Sol / Terra / Luna. The real OpenAI model ids live here and nowhere
else - nothing outside this module should hardcode an OpenAI model string.

This module deliberately imports nothing from `app` and nothing from Flask, so
it is safe to import from app.py, from any service, and from migration scripts
without circular-import risk. Anything that needs the database (plan lookup,
per-chatbot resolution) lives in app.py next to get_user_plan().
"""
from collections import namedtuple

ModelProfile = namedtuple('ModelProfile', [
    'alias',                 # stable key stored in the DB: 'sol' | 'terra' | 'luna'
    'display_name',          # 'Sol'
    'blurb',                 # one-line copy for the picker
    'model_id',              # real OpenAI id, server-side only
    'rank',                  # 0 = cheapest; drives ordering and best/cheapest_allowed
    'chat_token_param',      # param name for client.chat.completions.create
    'responses_token_param', # param name for client.responses.create
    'supports_temperature',  # False => omit temperature entirely
    'simple_prompt',         # True => use the short KB-generation prompt
    'training_max_tokens',   # completion budget for knowledge-base generation
    'kb_map_input_tokens',   # source text inlined in ONE knowledge-base call
    'user_selectable',       # False for internal-only entries (web search)
])

CATALOG = {
    'luna': ModelProfile(
        alias='luna', display_name='Luna',
        blurb='Fast and economical. Best for high-volume FAQ and support bots.',
        model_id='gpt-5-mini', rank=0,
        chat_token_param='max_completion_tokens',
        responses_token_param='max_output_tokens',
        supports_temperature=False, simple_prompt=True,
        training_max_tokens=16000, kb_map_input_tokens=60000, user_selectable=True,
    ),
    'terra': ModelProfile(
        alias='terra', display_name='Terra',
        blurb='Balanced quality and cost. A good default for most chatbots.',
        model_id='gpt-4.1', rank=1,
        chat_token_param='max_tokens',
        responses_token_param='max_output_tokens',
        supports_temperature=True, simple_prompt=False,
        # Terra takes the smallest input slice: a knowledge base built from 60k
        # tokens of input does not fit in one reply, and the overflow shows up
        # as JSON truncated mid-object.
        #
        # The output budget is what actually binds. At 4000 it truncated the
        # knowledge base for a 13k-character corpus - five small documents -
        # and failed the run with kb_invalid_json. gpt-4.1 allows 32k output
        # tokens, so 16000 matches the other tiers and is still half the cap.
        # Nothing bills for an unused budget: a run pays for what it generates.
        training_max_tokens=16000, kb_map_input_tokens=24000, user_selectable=True,
    ),
    'sol': ModelProfile(
        alias='sol', display_name='Sol',
        blurb='Our most capable model. Best reasoning, highest cost.',
        model_id='gpt-5', rank=2,
        chat_token_param='max_completion_tokens',
        responses_token_param='max_output_tokens',
        supports_temperature=False, simple_prompt=True,
        training_max_tokens=16000, kb_map_input_tokens=60000, user_selectable=True,
    ),
}

DEFAULT_ALIAS = 'terra'    # safe fallback: mid tier, never silently upgrades to Sol
CHEAPEST_ALIAS = 'luna'

# Internal only. Kept out of CATALOG so it can never be picked or plan-gated.
# Web search requires this specific model and only works via chat.completions.
WEB_SEARCH_PROFILE = ModelProfile(
    alias='__web_search', display_name='Web Search', blurb='',
    model_id='gpt-4o-search-preview', rank=1,
    chat_token_param='max_tokens',
    responses_token_param='max_output_tokens',
    supports_temperature=True, simple_prompt=False,
    training_max_tokens=4000, kb_map_input_tokens=24000, user_selectable=False,
)

# Retrieval embeddings. Internal only, and deliberately NOT plan-gated: search
# quality is a property of the product, not of the tier a customer pays for - a
# Luna bot and a Sol bot search the same index the same way. Kept out of CATALOG
# so it can never appear in a picker or be caught by filter_allowed().
#
# 512 dimensions rather than the native 1536: text-embedding-3-small supports
# Matryoshka truncation with negligible retrieval loss at our corpus sizes, and
# it is the difference between a 4 MB artifact and a 27 MB one that gets re-read
# on every chat message.
EmbeddingProfile = namedtuple('EmbeddingProfile', [
    'model_id',
    'dimensions',
    'max_batch',          # texts per embeddings request
    'max_input_tokens',   # per text; longer chunks are truncated by the API
])

EMBEDDING_PROFILE = EmbeddingProfile(
    model_id='text-embedding-3-small',
    dimensions=512,
    max_batch=96,
    max_input_tokens=8000,
)


# Every raw model id the platform could have written before the tier rework:
# the six legacy dropdown options plus the two hardcoded code defaults.
LEGACY_MODEL_MAP = {
    'gpt-5': 'sol',
    'gpt-5-mini': 'luna',
    'gpt-4': 'terra',
    'gpt-4o-mini': 'luna',
    'gpt-4.1': 'terra',
    'gpt-4.1-mini': 'luna',
    'gpt-4o': 'terra',        # what the trainer was actually using
    'gpt-3.5-turbo': 'luna',  # the old chat-service default
}


def normalize_alias(value):
    """Accept an alias, a legacy raw model id, or junk. Always return a valid alias."""
    if not value:
        return DEFAULT_ALIAS
    v = str(value).strip().lower()
    if v in CATALOG:
        return v
    if v in LEGACY_MODEL_MAP:
        return LEGACY_MODEL_MAP[v]
    return DEFAULT_ALIAS


def get_profile(value):
    """Profile for an alias / legacy id / junk. Never raises."""
    return CATALOG[normalize_alias(value)]


def resolve_model_id(value):
    """The real OpenAI model id to send to the API."""
    return get_profile(value).model_id


def selectable_profiles():
    """Ordered cheapest -> most capable, for pickers and admin checkboxes."""
    return sorted((p for p in CATALOG.values() if p.user_selectable), key=lambda p: p.rank)


def all_aliases():
    return [p.alias for p in selectable_profiles()]


def filter_allowed(aliases):
    """Drop anything not in the catalog; return a de-duped, rank-ordered list."""
    seen = {str(a).strip().lower() for a in (aliases or [])}
    return [p.alias for p in selectable_profiles() if p.alias in seen]


def best_allowed(aliases):
    """Most capable alias in the list, falling back to the cheapest tier."""
    allowed = filter_allowed(aliases) or [CHEAPEST_ALIAS]
    return allowed[-1]


def cheapest_allowed(aliases):
    """Cheapest alias in the list, falling back to the cheapest tier."""
    allowed = filter_allowed(aliases) or [CHEAPEST_ALIAS]
    return allowed[0]


def apply_chat_params(api_params, profile, max_tokens=None, temperature=None):
    """Set the token-budget and temperature params a given tier actually accepts.

    Replaces the old model-name prefix matching: gpt-5 family models require
    max_completion_tokens and reject a non-default temperature, while gpt-4.1
    takes max_tokens and accepts temperature.
    """
    if max_tokens is not None:
        api_params[profile.chat_token_param] = max_tokens
    if temperature is not None and profile.supports_temperature:
        api_params['temperature'] = temperature
    return api_params


def extract_usage(response):
    """Normalize token usage from either the Responses API or Chat Completions.

    Returns {'prompt_tokens', 'completion_tokens', 'total_tokens'} or None when
    no usage was reported. Never raises - a metering failure must not break a
    chat reply.
    """
    try:
        u = getattr(response, 'usage', None)
        if u is None:
            return None
        prompt = getattr(u, 'input_tokens', None)          # Responses API
        if prompt is None:
            prompt = getattr(u, 'prompt_tokens', None)     # Chat Completions
        completion = getattr(u, 'output_tokens', None)
        if completion is None:
            completion = getattr(u, 'completion_tokens', None)
        prompt = int(prompt or 0)
        completion = int(completion or 0)
        total = getattr(u, 'total_tokens', None)
        total = int(total) if total else (prompt + completion)
        if total == 0:
            return None
        return {
            'prompt_tokens': prompt,
            'completion_tokens': completion,
            'total_tokens': total,
        }
    except Exception:
        return None
