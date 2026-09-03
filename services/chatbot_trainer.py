"""Turn a chatbot's uploaded documents into something it can answer from.

Training produces one artifact per chatbot at training_data/chatbot_{id}.json:
a structured knowledge base (facts and Q&A patterns distilled by the model) plus
a vector index over the source text (chunks embedded with OpenAI embeddings).

Two rules this module exists to enforce, both of them reactions to how it used
to behave:

1. **No silent success.** Training either writes a complete artifact or raises
   TrainingError. It used to swallow every exception, fall through to a
   sentence-splitting "legacy" mode that stored `"embeddings": null`, and let the
   caller report "Chatbot trained successfully!". Every historical bug report
   about a chatbot that "forgot everything" is that fallback.
2. **Never destroy working training.** The artifact is replaced atomically, and
   only after the whole pipeline has succeeded. A failed retrain leaves the
   previous one byte-identical and still answering.

The legacy sentence format is still *read* - existing bots must keep working
until their owner retrains - but it is never written again.
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from openai import OpenAI

from services.embedding_service import EmbeddingService, get_embedding_service
from services.model_catalog import (DEFAULT_ALIAS, apply_chat_params, extract_usage,
                                    get_profile, EMBEDDING_PROFILE)
from services.object_storage import (PRIVATE, StorageError, StorageNotFound,
                                     artifact_key, chat_read_timeout, get_storage)
from services.openai_retry import OpenAICallFailed, call_with_retry
from services.text_chunker import batch_text, chunk_documents, group_for_map
from services.training_errors import TrainingError

# Guards, checked before any OpenAI call so an over-limit corpus costs nothing.
MAX_TRAINING_CHARS = int(os.environ.get('TRAINING_MAX_CHARS', 1500000))
MAX_TRAINING_CHUNKS = int(os.environ.get('TRAINING_MAX_CHUNKS', 1500))
MIN_TRAINING_CHARS = 200
TRAINING_CALL_TIMEOUT = float(os.environ.get('TRAINING_CALL_TIMEOUT', 180))

SCHEMA_VERSION = 3

# Artifacts live in object storage and are read on every chat message, so the
# cache is not an optimization - without it each message would pull megabytes
# over the network. The key is a *version string*, and Chatbot.last_training_run_id
# is that string: it changes exactly when a training run succeeds, so no stat, no
# HEAD, and no round trip is needed to know whether the cached copy is current.
# The write-through in train_chatbot() means the first chat after a run is a hit.
_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 8      # a miss now costs a network round trip, not a local read
_CACHE_MAX_BYTES = 48 * 1024 * 1024

# Returned when an artifact was loaded without a known version. It can never
# equal a real run id, so the next versioned read refreshes it.
UNKNOWN_VERSION = '?'

_trainer = None
_trainer_lock = threading.Lock()


def artifact_version(chatbot):
    """The cache version for a chatbot's artifact.

    last_training_run_id changes precisely when a run succeeds, so it is a free
    ETag - the chat path already has the Chatbot row loaded.
    """
    if chatbot is None:
        return None
    return (getattr(chatbot, 'last_training_run_id', None)
            or (chatbot.last_trained_at.isoformat()
                if getattr(chatbot, 'last_trained_at', None) else None)
            or UNKNOWN_VERSION)


class ChatbotTrainer:
    def __init__(self, embedding_service=None):
        self.api_key = os.getenv('OPENAI_API_KEY')
        if self.api_key:
            # max_retries=0 because services/openai_retry.py owns retrying. The
            # SDK's default of 2 would multiply with ours into 12 real calls.
            self.openai_client = OpenAI(api_key=self.api_key, max_retries=0, timeout=60.0)
        else:
            self.openai_client = None
            print("WARNING: OPENAI_API_KEY not found. Training will refuse to run.")

        self.embeddings = embedding_service or get_embedding_service()

    def artifact_key(self, chatbot_id):
        return artifact_key(chatbot_id)

    # ------------------------------------------------------------------
    # Knowledge-base generation
    # ------------------------------------------------------------------

    def _kb_prompt(self, text, profile, chatbot_info=None, part=None, parts=None):
        brand_name = chatbot_info.get('name', 'the business') if chatbot_info else 'the business'
        brand_desc = chatbot_info.get('description', '') if chatbot_info else ''

        # A batch is one slice of a larger corpus. Say so, or the model invents
        # continuity ("as mentioned above") with text it was never shown.
        preamble = ''
        if parts and parts > 1:
            preamble = (f"This is part {part} of {parts} of a larger document set. "
                        f"Extract only what appears in THIS part. Omit sections you have "
                        f"no information for. Do not invent continuity with other parts.\n\n")

        if profile.simple_prompt:
            return preamble + f"""Convert this document into a structured JSON knowledge base for a chatbot.

Business: {brand_name}
Description: {brand_desc}

Extract ONLY information from the document below. Use exactly these field names:

{{
  "brand": {{"name": "", "mission": "", "target_audience": "", "location": "", "contact_info": "", "website": ""}},
  "business_info": {{"products": [], "services": [], "pricing": "", "hours": "", "specialties": []}},
  "routing_hints": {{"global_keywords": []}},
  "kb_facts": [{{"id": "", "title": "", "keywords": [], "answer_short": "", "answer_long": "", "category": ""}}],
  "qa_patterns": [{{"intent_id": "", "triggers": [], "response_inline": ""}}]
}}

"title" is the question or topic. "keywords" are search terms a user might type.
Do not rename these fields.

Document:
{text}

Return valid JSON only."""

        return preamble + f"""You are an AI assistant that converts raw document text into a structured JSON knowledge base for a chatbot.

The chatbot is for: {brand_name}
Description: {brand_desc}

CRITICAL INSTRUCTIONS:
- You MUST extract information ONLY from the document text provided below
- DO NOT use any example data, sample data, or placeholder information
- DO NOT invent or fabricate any information not present in the documents
- If the documents don't contain certain information, omit those sections or use minimal placeholder text
- All kb_facts and qa_patterns must be derived exclusively from the actual document content

Convert the following document text into a structured JSON knowledge base that the chatbot can use to answer questions.

The JSON should follow this exact structure (but use ONLY data from the documents, not this example structure):
{{
  "version": "1.0",
  "brand": {{
    "name": "Business Name",
    "mission": "Mission statement or business purpose",
    "target_audience": "Target audience description",
    "location": "Business location if mentioned",
    "contact_info": "Contact information if available",
    "website": "Website URL if mentioned"
  }},
  "business_info": {{
    "products": ["Product 1", "Product 2"],
    "services": ["Service 1", "Service 2"],
    "plans": [
      {{
        "name": "Plan Name",
        "price": "Price",
        "features": ["Feature 1", "Feature 2"],
        "description": "Plan description"
      }}
    ],
    "pricing": "Pricing information",
    "hours": "Business hours if mentioned",
    "specialties": ["Specialty 1", "Specialty 2"]
  }},
  "routing_hints": {{
    "global_keywords": ["keyword1", "keyword2", "..."],
    "urls": {{
      "page_name": "/url-path"
    }}
  }},
  "kb_facts": [
    {{
      "id": "unique-id",
      "title": "Fact title or question",
      "keywords": ["keyword1", "keyword2"],
      "answer_short": "Brief answer",
      "answer_long": "Detailed answer",
      "category": "Product|Service|Pricing|General|Support"
    }}
  ],
  "qa_patterns": [
    {{
      "intent_id": "unique-intent-id",
      "triggers": ["question variation 1", "question variation 2"],
      "response_inline": "Direct answer text",
      "response_ref": "kb_facts id to reference (optional)"
    }}
  ]
}}

IMPORTANT EXTRACTION GUIDELINES:
1. BUSINESS IDENTIFICATION: Extract the business name, what they do, their mission/purpose
2. PRODUCTS & SERVICES: Identify all products, services, plans, or offerings mentioned
3. PRICING INFORMATION: Extract any pricing, plans, packages, or cost information
4. LOCATION & CONTACT: Find business location, contact information, hours of operation
5. SPECIALTIES: Identify what makes this business unique or their areas of expertise
6. PROCESSES: Extract any how-to information, procedures, or step-by-step processes
7. FAQ CONTENT: Convert Q&A pairs into structured kb_facts and qa_patterns
8. KEYWORDS: Generate relevant keywords for each fact to improve search matching
9. CATEGORIZATION: Categorize each fact (Product, Service, Pricing, General, Support)
10. COMPREHENSIVE COVERAGE: Create entries for all important information, not just Q&A pairs

SPECIFIC EXTRACTION PRIORITIES:
- Business name and description (even if not explicitly stated)
- All products, services, or offerings mentioned
- Pricing information, plans, packages
- Business location and contact details
- Hours of operation or availability
- Unique selling points or specialties
- Common questions and their answers
- Process or procedure information
- Any URLs, links, or references

REMEMBER: Use ONLY the document text below. No external information, no sample data.

Document text to convert (THIS IS THE ONLY SOURCE OF INFORMATION):
---BEGIN DOCUMENT TEXT---
{text}
---END DOCUMENT TEXT---

Return ONLY the JSON structure with data extracted from the document text above. No additional explanation, no sample data."""

    @staticmethod
    def _strip_json_fence(raw):
        text = (raw or '').strip()
        if text.startswith('```json'):
            text = text[7:]
        elif text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        return text.strip()

    def _kb_call(self, prompt, profile, *, op, usage_sink, deadline, logger, counter):
        """One knowledge-base completion, retried, parsed, validated."""
        api_params = {
            "model": profile.model_id,
            "messages": [
                {"role": "system", "content": "You are an expert at converting documents into structured knowledge bases for chatbots."},
                {"role": "user", "content": prompt}
            ],
            "timeout": TRAINING_CALL_TIMEOUT,
        }
        # The tier decides which token-budget parameter it accepts and whether a
        # non-default temperature is allowed. Reasoning tiers spend part of their
        # budget on reasoning tokens before emitting any JSON, which is why their
        # training_max_tokens is much larger.
        apply_chat_params(api_params, profile,
                          max_tokens=profile.training_max_tokens,
                          temperature=0.3)

        response = call_with_retry(
            lambda: self.openai_client.chat.completions.create(**api_params),
            op=op, attempts=4, base_delay=1.0, deadline=deadline,
            logger=logger, counter=counter)

        usage = extract_usage(response)
        if usage and usage_sink is not None:
            usage_sink.append(usage)

        raw = (response.choices[0].message.content or '').strip()
        if not raw:
            # Reasoning tiers can burn the whole completion budget on reasoning
            # and return nothing. That used to look like "training succeeded".
            raise TrainingError('kb_empty', f"{profile.display_name} returned an empty response",
                                phase='kb_generating')

        text = self._strip_json_fence(raw)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise TrainingError('kb_invalid_json',
                                f"model returned invalid JSON ({error}); first 200 chars: {text[:200]}",
                                phase='kb_generating')
        if not isinstance(data, dict):
            raise TrainingError('kb_invalid_json',
                                f"model returned {type(data).__name__}, expected an object",
                                phase='kb_generating')
        return data, usage

    def generate_knowledge_base(self, chunks, chatbot_info=None, usage_sink=None,
                                model_alias=None, progress=None, logger=None,
                                deadline=None, counter=None):
        """Build the knowledge base from chunked document text.

        `chunks` is the chunk list from services.text_chunker (a plain string is
        accepted and chunked here, for callers that predate the change).

        The model tier comes from `model_alias` - resolved per chatbot by the
        caller. It used to be read from the global 'openai_model' setting here,
        which meant a customer paying for Sol still trained on whatever the admin
        had picked platform-wide.
        """
        if not self.openai_client:
            raise TrainingError('no_api_key', 'OPENAI_API_KEY is not configured',
                                phase='kb_generating')

        if isinstance(chunks, str):
            chunks = chunk_documents([(None, chunks)])
        chunks = list(chunks or [])
        if not chunks:
            raise TrainingError('no_text_extracted', 'no text to build a knowledge base from',
                                phase='kb_generating')

        profile = get_profile(model_alias or DEFAULT_ALIAS)
        batches = group_for_map(chunks, profile.kb_map_input_tokens)
        partials = []

        for index, batch in enumerate(batches, start=1):
            started = time.monotonic()
            prompt = self._kb_prompt(batch_text(batch), profile, chatbot_info,
                                     part=index, parts=len(batches))
            partial, usage = self._kb_call(
                prompt, profile, op='chat.kb_map', usage_sink=usage_sink,
                deadline=deadline, logger=logger, counter=counter)
            partial = self._normalize_kb(partial)
            partials.append(partial)

            if logger:
                logger.event('training.kb.map', batch=index, batches=len(batches),
                             input_tokens=sum(c.get('tokens', 0) for c in batch),
                             output_tokens=(usage or {}).get('completion_tokens', 0),
                             facts=len(partial.get('kb_facts') or []),
                             ms=int((time.monotonic() - started) * 1000))
            if progress:
                progress('kb_generating', 70 + int(18.0 * index / max(1, len(batches))),
                         f"Building knowledge base ({index} of {len(batches)})...")

        if len(partials) == 1:
            # Identical to the old single-shot behaviour, so nothing changes for
            # the small corpora that make up most of the customer base.
            merged = partials[0]
            merged['degraded'] = False
        else:
            if progress:
                progress('kb_merging', 90, 'Merging knowledge base...')
            merged = self._merge_partials(partials, profile, usage_sink=usage_sink,
                                          deadline=deadline, logger=logger, counter=counter)

        if not (merged.get('kb_facts') or merged.get('qa_patterns')):
            raise TrainingError('kb_empty', 'the model extracted no facts from these documents',
                                phase='kb_generating')
        return merged

    # -- reduce ---------------------------------------------------------

    @staticmethod
    def _norm_key(value):
        return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()

    # Field names models actually emit instead of the ones we ask for. Left as
    # data rather than prompt-wrangling, because a knowledge base whose facts
    # cannot be matched is indistinguishable to a user from no training at all.
    _FACT_ALIASES = {
        'title': ('title', 'question', 'name', 'topic', 'heading'),
        'answer_long': ('answer_long', 'answer', 'response', 'answer_full', 'detail', 'details'),
        'answer_short': ('answer_short', 'short_answer', 'summary', 'answer', 'response'),
        'category': ('category', 'type', 'section'),
        'id': ('id', 'fact_id', 'key'),
    }
    _PATTERN_ALIASES = {
        'intent_id': ('intent_id', 'id', 'intent'),
        'triggers': ('triggers', 'questions', 'variations', 'utterances', 'examples'),
        'response_inline': ('response_inline', 'response', 'answer', 'reply'),
        'response_ref': ('response_ref', 'ref', 'fact_id'),
    }
    _STOPWORDS = {'what', 'when', 'where', 'which', 'who', 'how', 'why', 'is', 'are', 'the',
                  'a', 'an', 'do', 'does', 'did', 'can', 'your', 'you', 'our', 'we', 'of',
                  'for', 'to', 'in', 'on', 'at', 'and', 'or', 'it', 'this', 'that', 'with'}

    @classmethod
    def _pick(cls, source, names):
        for name in names:
            value = source.get(name)
            if value not in (None, '', [], {}):
                return value
        return None

    @classmethod
    def _normalize_kb(cls, data):
        """Coerce a model's knowledge base into the schema retrieval expects.

        query_knowledge_base() scores on title and keywords. A fact that arrives
        as {"question": ..., "answer": ...} scores zero against every query, so
        the bot answers "I don't have that information" while its training data
        looks perfectly fine in the viewer.
        """
        facts = []
        for index, raw in enumerate(data.get('kb_facts') or [], start=1):
            if not isinstance(raw, dict):
                continue
            title = cls._pick(raw, cls._FACT_ALIASES['title'])
            answer_long = cls._pick(raw, cls._FACT_ALIASES['answer_long'])
            answer_short = cls._pick(raw, cls._FACT_ALIASES['answer_short'])
            if not (title or answer_long or answer_short):
                continue

            keywords = raw.get('keywords')
            if not isinstance(keywords, list) or not keywords:
                # Derive them from the title so the fact is findable at all.
                words = re.findall(r'[a-z0-9]+', str(title or '').lower())
                keywords = [w for w in words if w not in cls._STOPWORDS and len(w) > 2]
            fact = dict(raw)
            fact.update({
                'id': str(cls._pick(raw, cls._FACT_ALIASES['id']) or 'f%04d' % index),
                'title': str(title or (answer_short or answer_long or '')[:80]),
                'answer_long': str(answer_long or answer_short or ''),
                'answer_short': str(answer_short or answer_long or '')[:300],
                'category': str(cls._pick(raw, cls._FACT_ALIASES['category']) or 'General'),
                'keywords': [str(k) for k in keywords][:20],
            })
            facts.append(fact)

        patterns = []
        for index, raw in enumerate(data.get('qa_patterns') or [], start=1):
            if not isinstance(raw, dict):
                continue
            triggers = cls._pick(raw, cls._PATTERN_ALIASES['triggers'])
            if isinstance(triggers, str):
                triggers = [triggers]
            response = cls._pick(raw, cls._PATTERN_ALIASES['response_inline'])
            if not triggers and not response:
                continue
            pattern = dict(raw)
            pattern.update({
                'intent_id': str(cls._pick(raw, cls._PATTERN_ALIASES['intent_id']) or 'i%04d' % index),
                'triggers': [str(t) for t in (triggers or [])][:20],
                'response_inline': str(response or ''),
            })
            patterns.append(pattern)

        # Every fact's title is also a usable trigger. Without this, a knowledge
        # base with facts but no qa_patterns (common on the reasoning tiers) has
        # nothing for exact-phrase matching to hit.
        known = {cls._norm_key(t) for p in patterns for t in p.get('triggers', [])}
        for fact in facts:
            key = cls._norm_key(fact['title'])
            if key and key not in known and fact.get('answer_long'):
                patterns.append({
                    'intent_id': 'i%04d' % (len(patterns) + 1),
                    'triggers': [fact['title']],
                    'response_inline': fact['answer_short'] or fact['answer_long'],
                    'response_ref': fact['id'],
                })
                known.add(key)

        normalized = dict(data)
        normalized['kb_facts'] = facts
        normalized['qa_patterns'] = patterns

        hints = normalized.get('routing_hints')
        if not isinstance(hints, dict):
            hints = {}
        if not hints.get('global_keywords'):
            collected = []
            for fact in facts:
                collected.extend(fact.get('keywords') or [])
            hints['global_keywords'] = list(dict.fromkeys(collected))[:200]
        normalized['routing_hints'] = hints
        return normalized

    def _merge_partials(self, partials, profile, *, usage_sink, deadline, logger, counter):
        """Merge per-batch knowledge bases.

        The bulk arrays are merged deterministically in Python - sending hundreds
        of facts back through the model just to combine them would truncate on
        the output budget, which is the failure this whole design avoids. Only
        the small narrative fields (brand, business_info) go through one cheap
        model call, and even that degrades to a local merge rather than failing.
        """
        started = time.monotonic()
        facts, fact_order = {}, []
        patterns, pattern_order = {}, []
        keywords, urls = [], {}
        # Every original fact id that collapsed into a given merge key. Without
        # this, a qa_pattern pointing at the *dropped* copy of a duplicated fact
        # loses its response_ref entirely.
        aliases = {}

        for partial in partials:
            for fact in (partial.get('kb_facts') or []):
                if not isinstance(fact, dict):
                    continue
                key = self._norm_key(fact.get('title')) or self._norm_key(fact.get('id')) or str(len(facts))
                if fact.get('id'):
                    aliases.setdefault(key, []).append(str(fact['id']))
                existing = facts.get(key)
                if existing is None:
                    facts[key] = dict(fact)
                    fact_order.append(key)
                    continue
                # Same fact seen twice (chunks overlap on purpose): keep the
                # fuller answer and union the keywords.
                if len(str(fact.get('answer_long') or '')) > len(str(existing.get('answer_long') or '')):
                    existing['answer_long'] = fact.get('answer_long')
                if len(str(fact.get('answer_short') or '')) > len(str(existing.get('answer_short') or '')):
                    existing['answer_short'] = fact.get('answer_short')
                merged_keywords = list(existing.get('keywords') or []) + list(fact.get('keywords') or [])
                existing['keywords'] = list(dict.fromkeys(merged_keywords))

            for pattern in (partial.get('qa_patterns') or []):
                if not isinstance(pattern, dict):
                    continue
                key = self._norm_key(pattern.get('intent_id')) or self._norm_key(
                    (pattern.get('triggers') or [''])[0]) or str(len(patterns))
                existing = patterns.get(key)
                if existing is None:
                    patterns[key] = dict(pattern)
                    pattern_order.append(key)
                    continue
                merged_triggers = list(existing.get('triggers') or []) + list(pattern.get('triggers') or [])
                existing['triggers'] = list(dict.fromkeys(merged_triggers))
                if len(str(pattern.get('response_inline') or '')) > len(str(existing.get('response_inline') or '')):
                    existing['response_inline'] = pattern.get('response_inline')

            hints = partial.get('routing_hints') or {}
            keywords.extend(hints.get('global_keywords') or [])
            if isinstance(hints.get('urls'), dict):
                urls.update(hints['urls'])

        # Re-id, then rewrite every response_ref through the id map so the
        # qa_pattern -> kb_fact links survive deduplication.
        id_map = {}
        kb_facts = []
        for position, key in enumerate(fact_order, start=1):
            fact = facts[key]
            new_id = 'f%04d' % position
            for original in aliases.get(key, []):
                id_map[original] = new_id
            if fact.get('id'):
                id_map[str(fact['id'])] = new_id
            id_map[key] = new_id
            fact['id'] = new_id
            kb_facts.append(fact)

        qa_patterns = []
        for position, key in enumerate(pattern_order, start=1):
            pattern = patterns[key]
            pattern['intent_id'] = 'i%04d' % position
            ref = pattern.get('response_ref')
            if ref:
                pattern['response_ref'] = id_map.get(str(ref), id_map.get(self._norm_key(ref)))
            qa_patterns.append(pattern)

        brand, business_info, degraded = self._merge_narrative(
            partials, profile, usage_sink=usage_sink, deadline=deadline,
            logger=logger, counter=counter)

        merged = {
            'version': '1.0',
            'brand': brand,
            'business_info': business_info,
            'routing_hints': {
                'global_keywords': list(dict.fromkeys(keywords))[:200],
                'urls': urls,
            },
            'kb_facts': kb_facts,
            'qa_patterns': qa_patterns,
            'degraded': degraded,
        }
        if logger:
            logger.event('training.kb.reduce', partials=len(partials),
                         facts_out=len(kb_facts), qa_out=len(qa_patterns),
                         degraded=degraded,
                         ms=int((time.monotonic() - started) * 1000))
        return merged

    def _merge_narrative(self, partials, profile, *, usage_sink, deadline, logger, counter):
        """Merge brand/business_info. Returns (brand, business_info, degraded)."""
        payload = [{'brand': p.get('brand') or {}, 'business_info': p.get('business_info') or {}}
                   for p in partials]
        prompt = (
            "Merge these partial business descriptions, extracted from different parts of "
            "one document set, into ONE deduplicated JSON object with exactly two keys: "
            "\"brand\" and \"business_info\". Keep the same field names. Do not invent "
            "anything that is not present. Return valid JSON only.\n\n"
            + json.dumps(payload, ensure_ascii=False)[:60000]
        )
        try:
            data, _usage = self._kb_call(prompt, profile, op='chat.kb_reduce',
                                         usage_sink=usage_sink, deadline=deadline,
                                         logger=logger, counter=counter)
            brand = data.get('brand') or {}
            business_info = data.get('business_info') or {}
            if brand or business_info:
                return brand, business_info, False
        except Exception as error:
            # Degrade rather than fail: the facts are already extracted and real,
            # and only the brand/business_info blurb is at stake. Deliberately
            # broad - no failure of this cosmetic step should cost a user a run
            # whose expensive half already succeeded. This is recorded on the run
            # row and in the log, so unlike the fallback this phase removed,
            # nothing here claims work that did not happen.
            if logger:
                logger.warning('training.kb.reduce_degraded', error_type=type(error).__name__,
                               detail=str(error)[:200])

        brand = {}
        business_info = {}
        for partial in partials:
            candidate = partial.get('brand') or {}
            if not brand and candidate.get('name'):
                brand = dict(candidate)
            for key, value in (partial.get('business_info') or {}).items():
                if isinstance(value, list):
                    existing = business_info.setdefault(key, [])
                    if isinstance(existing, list):
                        for item in value:
                            if item not in existing:
                                existing.append(item)
                elif value and not business_info.get(key):
                    business_info[key] = value
        return brand, business_info, True

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train_chatbot(self, chatbot_id, documents_text, *, chatbot_info=None,
                      model_alias=None, usage_sink=None, embedding_usage_sink=None,
                      progress=None, run_id=None, deadline=None, logger=None,
                      counter=None):
        """Build and persist a chatbot's artifact. Returns a summary dict.

        `documents_text` is [(source_label, text), ...] - per document, so a
        retrieved passage can name the file it came from.

        Raises TrainingError on any failure, having written nothing. There is no
        success path that skips the artifact.
        """
        if not self.openai_client:
            raise TrainingError('no_api_key', 'OPENAI_API_KEY is not configured')

        documents_text = [(source, text or '') for source, text in (documents_text or [])]

        empty = [source for source, text in documents_text if len((text or '').strip()) == 0]
        total_chars = sum(len(text) for _source, text in documents_text)
        meaningful = sum(len((text or '').strip()) for _source, text in documents_text)

        # Guards run before any API call, so an unusable corpus costs nothing.
        if empty:
            raise TrainingError('no_text_extracted',
                                'no text could be extracted from: ' + ', '.join(empty),
                                phase='extracting', files=', '.join(empty))
        if meaningful < MIN_TRAINING_CHARS:
            raise TrainingError('no_text_extracted',
                                f'only {meaningful} characters of text were extracted',
                                phase='extracting',
                                files=', '.join(s or 'document' for s, _t in documents_text))
        if total_chars > MAX_TRAINING_CHARS:
            raise TrainingError('corpus_too_large',
                                f'{total_chars} characters exceeds the {MAX_TRAINING_CHARS} limit',
                                phase='extracting',
                                chars=f'{total_chars:,}', limit=f'{MAX_TRAINING_CHARS:,}')

        if progress:
            progress('chunking', 30, 'Splitting documents into sections...')
        chunks = chunk_documents(documents_text)
        if not chunks:
            raise TrainingError('no_text_extracted', 'chunking produced no sections',
                                phase='chunking', files='the uploaded documents')
        if len(chunks) > MAX_TRAINING_CHUNKS:
            raise TrainingError('too_many_chunks',
                                f'{len(chunks)} sections exceeds the {MAX_TRAINING_CHUNKS} limit',
                                phase='chunking',
                                chunks=f'{len(chunks):,}', limit=f'{MAX_TRAINING_CHUNKS:,}')
        if logger:
            logger.event('training.chunk.done', chunk_count=len(chunks),
                         est_tokens=sum(c.get('tokens', 0) for c in chunks),
                         avg_chunk_tokens=int(sum(c.get('tokens', 0) for c in chunks) / len(chunks)))

        # Embed first: it is the cheaper half, so a quota or auth problem surfaces
        # before we spend knowledge-base money on a run that cannot finish.
        if progress:
            progress('embedding', 35, f'Indexing {len(chunks)} sections...')

        def embed_progress(done, total):
            if progress:
                progress('embedding', 35 + int(30.0 * done / max(1, total)),
                         f'Indexing sections ({done} of {total})...')

        embed_started = time.monotonic()
        try:
            vectors = self.embeddings.embed_documents(
                [c['text'] for c in chunks], progress=embed_progress,
                usage_sink=embedding_usage_sink, deadline=deadline,
                counter=counter, logger=logger)
        except OpenAICallFailed as error:
            raise TrainingError(error.code, str(error), phase='embedding')
        if logger:
            logger.event('training.embed.done', chunk_count=len(vectors),
                         ms=int((time.monotonic() - embed_started) * 1000))

        if progress:
            progress('kb_generating', 70, 'Building knowledge base...')
        try:
            kb_data = self.generate_knowledge_base(
                chunks, chatbot_info=chatbot_info, usage_sink=usage_sink,
                model_alias=model_alias, progress=progress, logger=logger,
                deadline=deadline, counter=counter)
        except OpenAICallFailed as error:
            raise TrainingError(error.code, str(error), phase='kb_generating')

        if progress:
            progress('persisting', 95, 'Saving knowledge base...')

        sources = []
        for source, text in documents_text:
            sources.append({
                'filename': source,
                'chars': len(text),
                'chunks': sum(1 for c in chunks if c.get('source') == source),
            })

        artifact = dict(kb_data)
        artifact.update({
            'schema_version': SCHEMA_VERSION,
            'generated_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
            'run_id': run_id,
            'model_alias': model_alias or DEFAULT_ALIAS,
            'sources': sources,
        })
        if vectors:
            artifact['index'] = {
                'embedding_model': EMBEDDING_PROFILE.model_id,
                'dimensions': EMBEDDING_PROFILE.dimensions,
                'normalized': True,
                'count': len(vectors),
                'chunks': [{'id': c['id'], 'source': c.get('source'), 'ord': c['ord'],
                            'tokens': c.get('tokens'), 'text': c['text']}
                           for c in chunks[:len(vectors)]],
                'vectors_b64': EmbeddingService.encode_b64(vectors),
            }

        key = self.artifact_key(chatbot_id)
        written = self._store_artifact(chatbot_id, artifact, run_id=run_id)
        if logger:
            logger.event('training.persist', key=key, bytes=written,
                         facts=len(artifact.get('kb_facts') or []),
                         qa=len(artifact.get('qa_patterns') or []),
                         chunks=len(vectors))

        return {
            'chunk_count': len(chunks),
            'fact_count': len(artifact.get('kb_facts') or []),
            'qa_count': len(artifact.get('qa_patterns') or []),
            'char_count': total_chars,
            'bytes': written,
            'degraded': bool(artifact.get('degraded')),
        }

    def _store_artifact(self, chatbot_id, artifact, run_id=None):
        """Upload the artifact and prime the cache with it.

        A single PUT *is* the atomic replace - no temp key and rename, which
        would only add a second failure point and a window where two copies
        exist. If the PUT fails, nothing is written and the previous artifact
        remains the live one, so the bot keeps answering from the training it
        already had.
        """
        payload = json.dumps(artifact, ensure_ascii=False, indent=2).encode('utf-8')
        try:
            get_storage().put(PRIVATE, self.artifact_key(chatbot_id), payload,
                              content_type='application/json')
        except StorageError as error:
            raise TrainingError(error.code, str(error), phase='persisting')

        # Write-through. training_runner sets last_training_run_id to this same
        # run_id moments later, so the cached version and the database agree by
        # construction and the first chat after a run costs no network call.
        self._cache_store(chatbot_id, artifact, run_id or artifact.get('run_id')
                          or UNKNOWN_VERSION, len(payload))
        return len(payload)

    def _cache_store(self, chatbot_id, data, version, size):
        vectors = None
        index = data.get('index') if isinstance(data, dict) else None
        if isinstance(index, dict) and index.get('vectors_b64'):
            vectors = EmbeddingService.decode_b64(index['vectors_b64'],
                                                  index.get('dimensions'))
        with _CACHE_LOCK:
            _CACHE[chatbot_id] = {'version': version, 'data': data, 'vectors': vectors,
                                  'bytes': size, 'used': time.monotonic()}
            self._evict_locked()
        return data

    # ------------------------------------------------------------------
    # Reading training data
    # ------------------------------------------------------------------

    def get_training_data(self, chatbot_id, version=None):
        """A chatbot's artifact, from cache when possible.

        `version` is Chatbot.last_training_run_id (see artifact_version). Given
        one, the cache hits only when it matches, so a retrained bot refreshes.

        With `version=None` a cached copy is returned whatever its version, with
        no network call and no staleness check - that is what keeps the internal
        callers (which have only a chatbot_id) off the wire. The chat path and
        the training-data routes pass a version, and they are the ones that must
        never serve a previous generation.
        """
        with _CACHE_LOCK:
            entry = _CACHE.get(chatbot_id)
            if entry is not None and (version is None or entry['version'] == version):
                entry['used'] = time.monotonic()
                return entry['data']

        try:
            payload = get_storage().get(PRIVATE, self.artifact_key(chatbot_id),
                                        timeout=chat_read_timeout(), attempts=1)
        except StorageNotFound:
            with _CACHE_LOCK:
                _CACHE.pop(chatbot_id, None)
            return None
        except StorageError as error:
            # A slow or unreachable store must not cost a visitor their answer:
            # the caller falls back to answering without document context.
            print(f" WARNING: could not fetch training data for chatbot "
                  f"{chatbot_id}: {error}")
            return None

        try:
            data = json.loads(payload.decode('utf-8'))
        except Exception as error:
            print(f" DEBUG: Error parsing training data for chatbot {chatbot_id}: {error}")
            return None

        return self._cache_store(chatbot_id, data,
                                 version or data.get('run_id') or UNKNOWN_VERSION,
                                 len(payload))

    def prime(self, chatbot_id, version):
        """Ensure the cache holds this chatbot's artifact at `version`.

        One line on the chat path, costing nothing when the cache is warm.
        """
        return self.get_training_data(chatbot_id, version=version) is not None

    @staticmethod
    def _evict_locked():
        """LRU by last access, bounded by entry count and by total bytes."""
        while (len(_CACHE) > _CACHE_MAX_ENTRIES
               or sum(e['bytes'] for e in _CACHE.values()) > _CACHE_MAX_BYTES):
            if len(_CACHE) <= 1:
                return
            oldest = min(_CACHE.items(), key=lambda item: item[1]['used'])[0]
            _CACHE.pop(oldest, None)

    def is_knowledge_base_format(self, training_data):
        """True for a v3 artifact or a v1 knowledge base; False for legacy sentences."""
        if not training_data:
            return False
        if training_data.get('schema_version', 0) >= SCHEMA_VERSION:
            return True
        return 'kb_facts' in training_data or 'qa_patterns' in training_data

    def has_vector_index(self, training_data):
        index = (training_data or {}).get('index') or {}
        return bool(index.get('vectors_b64'))

    def get_vector_index(self, chatbot_id):
        """Returns (chunks, decoded_vectors) or None."""
        data = self.get_training_data(chatbot_id)
        if not self.has_vector_index(data):
            return None
        with _CACHE_LOCK:
            entry = _CACHE.get(chatbot_id)
            vectors = entry['vectors'] if entry else None
        if vectors is None:
            return None
        return data['index'].get('chunks') or [], vectors

    def search_chunks(self, chatbot_id, query, top_k=5, usage_sink=None,
                      min_score=0.20, logger=None):
        """Semantic search over the chunk index. Empty list if unavailable."""
        index = self.get_vector_index(chatbot_id)
        if not index:
            return []
        chunks, vectors = index

        query_vector = self.embeddings.embed_query(query, usage_sink=usage_sink,
                                                   logger=logger)
        if not query_vector:
            return []  # caller still has kb_facts to answer from

        scores = EmbeddingService.score(vectors, query_vector)
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)

        results = []
        for position, score in ranked[:max(1, top_k)]:
            if score < min_score or position >= len(chunks):
                continue
            chunk = chunks[position]
            results.append({
                'content': chunk.get('text', ''),
                'similarity': float(score),
                'index': position,
                'source': chunk.get('source'),
                'chunk_id': chunk.get('id'),
            })
        return results

    def query_knowledge_base(self, chatbot_id, user_query, top_k=3, training_data=None):
        """Keyword match over kb_facts and qa_patterns.

        Kept as-is: the distilled facts are what the chat prompt is tuned for,
        and semantic chunk search complements them rather than replacing them.
        """
        if training_data is None:
            training_data = self.get_training_data(chatbot_id)

        if not training_data:
            print(" DEBUG: No training data available")
            return None

        if not self.is_knowledge_base_format(training_data):
            print(" DEBUG: Training data is in legacy format, not knowledge base")
            return None

        kb_facts = training_data.get('kb_facts', [])
        qa_patterns = training_data.get('qa_patterns', [])

        query_lower = user_query.lower().strip()
        query_words = set(query_lower.split())
        if not query_words:
            return None

        qa_matches = []
        for pattern in qa_patterns:
            intent_id = pattern.get('intent_id', '')
            for trigger in pattern.get('triggers', []):
                trigger_lower = str(trigger).lower()
                trigger_words = set(trigger_lower.split())
                word_overlap = len(query_words.intersection(trigger_words))

                if query_lower in trigger_lower or trigger_lower in query_lower:
                    match_score = 1.0
                elif word_overlap >= len(query_words) * 0.6:  # 60% word overlap
                    match_score = 0.7 + (word_overlap / len(query_words)) * 0.3
                elif word_overlap > 0:
                    match_score = word_overlap / max(len(query_words), len(trigger_words))
                else:
                    continue

                qa_matches.append({
                    'type': 'qa_pattern',
                    'intent_id': intent_id,
                    'trigger': trigger,
                    'score': match_score,
                    'response_inline': pattern.get('response_inline'),
                    'response_ref': pattern.get('response_ref'),
                    'data': pattern
                })
                break  # Only count one match per pattern

        kb_matches = []
        for fact in kb_facts:
            title = str(fact.get('title', ''))
            keywords = fact.get('keywords', []) or []
            match_score = 0.0

            title_lower = title.lower()
            if title_lower and (query_lower in title_lower or title_lower in query_lower):
                match_score += 0.5
            else:
                title_overlap = len(query_words.intersection(set(title_lower.split())))
                if title_overlap > 0:
                    match_score += (title_overlap / len(query_words)) * 0.3

            keyword_matches = 0
            for keyword in keywords:
                keyword_lower = str(keyword).lower()
                if keyword_lower in query_lower or any(kw in keyword_lower for kw in query_words):
                    keyword_matches += 1
            if keyword_matches > 0 and keywords:
                match_score += (keyword_matches / len(keywords)) * 0.5

            if match_score > 0.1:
                kb_matches.append({
                    'type': 'kb_fact',
                    'fact_id': fact.get('id', ''),
                    'title': title,
                    'score': match_score,
                    'answer_short': fact.get('answer_short'),
                    'answer_long': fact.get('answer_long'),
                    'keywords': keywords,
                    'data': fact
                })

        all_matches = qa_matches + kb_matches
        all_matches.sort(key=lambda match: match['score'], reverse=True)

        return {
            'matches': all_matches[:top_k],
            'brand': training_data.get('brand', {}),
            'routing_hints': training_data.get('routing_hints', {})
        }

    def find_similar_content(self, chatbot_id, query, top_k=3, usage_sink=None,
                             logger=None):
        """Best available passage search for this chatbot's artifact format."""
        data = self.get_training_data(chatbot_id)
        if not data:
            return []

        if self.has_vector_index(data):
            return self.search_chunks(chatbot_id, query, top_k=top_k,
                                      usage_sink=usage_sink, logger=logger)

        # Legacy artifacts keep working until their owner retrains. `.get` rather
        # than `[...]`: a v1 knowledge base has no 'sentences' key at all, which
        # used to raise KeyError right here.
        sentences = data.get('sentences') or []
        if sentences:
            return self._simple_text_search(sentences, query, top_k)
        return self._kb_text_search(data, query, top_k)

    def _kb_text_search(self, training_data, query, top_k=3):
        """Passage search over a v1 knowledge base that has no vector index."""
        passages = []
        for fact in (training_data.get('kb_facts') or []):
            body = ' '.join(str(part) for part in
                            (fact.get('title'), fact.get('answer_short'), fact.get('answer_long'))
                            if part)
            if body:
                passages.append(body)
        for pattern in (training_data.get('qa_patterns') or []):
            body = pattern.get('response_inline')
            if body:
                passages.append(str(body))
        if not passages:
            return []
        return self._simple_text_search(passages, query, top_k)

    def get_sentence_by_index(self, chatbot_id, index):
        """Legacy-format helper, still used by the no-OpenAI local chat service."""
        training_data = self.get_training_data(chatbot_id)
        sentences = (training_data or {}).get('sentences') or []
        if 0 <= index < len(sentences):
            return sentences[index]
        return None

    def _simple_text_search(self, sentences, query, top_k=3):
        """Word-overlap search, for artifacts with no vector index."""
        query_words = set(query.lower().split())
        query_lower = query.lower()

        results = []
        for idx, sentence in enumerate(sentences):
            sentence_lower = sentence.lower()
            sentence_words = set(sentence_lower.split())

            word_overlap = len(query_words.intersection(sentence_words))

            partial_matches = 0
            for q_word in query_words:
                for s_word in sentence_words:
                    if len(q_word) > 3 and (q_word in s_word or s_word in q_word):
                        partial_matches += 0.5

            substring_score = 0
            for q_word in query_words:
                if len(q_word) > 3 and q_word in sentence_lower:
                    substring_score += 0.3

            total_matches = word_overlap + partial_matches + substring_score

            if total_matches > 0:
                score = total_matches / (len(query_words) + len(sentence_words) - word_overlap + 1)
                if query_lower in sentence_lower:
                    score *= 1.5
                results.append({
                    'content': sentence,
                    'similarity': min(score, 1.0),
                    'index': idx
                })

        if not results:
            for idx, sentence in enumerate(sentences):
                sentence_lower = sentence.lower()
                for q_word in query_words:
                    if len(q_word) > 2 and q_word in sentence_lower:
                        results.append({
                            'content': sentence,
                            'similarity': 0.2,
                            'index': idx
                        })
                        break

        results.sort(key=lambda item: item['similarity'], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def delete_chatbot_data(self, chatbot_id):
        """Best-effort removal. A failure here must not block deleting a chatbot."""
        with _CACHE_LOCK:
            _CACHE.pop(chatbot_id, None)
        try:
            return get_storage().delete(PRIVATE, self.artifact_key(chatbot_id))
        except StorageError as error:
            print(f" WARNING: could not delete training data for chatbot "
                  f"{chatbot_id}: {error}")
            return False

    def describe_training_data(self, chatbot_id, version=None):
        """Summarize an artifact for diagnostics. Never raises."""
        key = self.artifact_key(chatbot_id)
        summary = {'key': key, 'exists': False}
        data = self.get_training_data(chatbot_id, version=version)
        if not data:
            return summary
        summary['exists'] = True
        index = data.get('index') or {}
        summary.update({
            'schema_version': data.get('schema_version', 1),
            'is_knowledge_base': self.is_knowledge_base_format(data),
            'model_alias': data.get('model_alias'),
            'run_id': data.get('run_id'),
            'generated_at': data.get('generated_at'),
            'degraded': bool(data.get('degraded')),
            'kb_facts': len(data.get('kb_facts') or []),
            'qa_patterns': len(data.get('qa_patterns') or []),
            'sentences': len(data.get('sentences') or []),
            'indexed_chunks': index.get('count', 0),
            'embedding_model': index.get('embedding_model'),
        })
        return summary

    def diagnose_training_data(self, chatbot_id):
        """Print a human-readable summary. Returns True if an artifact exists."""
        summary = self.describe_training_data(chatbot_id)
        print(f"TRAINING DATA FOR CHATBOT {chatbot_id}")
        print("=" * 50)
        for key, value in summary.items():
            print(f"  {key}: {value}")
        if summary.get('exists') and not summary.get('indexed_chunks'):
            print("  NOTE: no vector index - retrain to enable semantic search.")
        return bool(summary.get('exists'))


def get_trainer():
    """Process-wide trainer.

    A singleton because the artifact cache lives on the module and each extra
    instance would mean another megabytes-sized copy of the same data.
    """
    global _trainer
    if _trainer is None:
        with _trainer_lock:
            if _trainer is None:
                _trainer = ChatbotTrainer()
    return _trainer
