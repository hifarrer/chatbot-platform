"""OpenAI embeddings for retrieval.

Replaces a sentence-transformers path that never actually ran in production -
the package is not in requirements-render.txt, so AI_AVAILABLE was False, every
artifact stored `"embeddings": null`, and "semantic search" was really word
overlap. This calls a real embeddings API that works everywhere the app runs.

One process singleton, shared by the trainer (batch, at training time) and the
chat service (one query, per message), so the model id, dimensions, batching and
retry policy have exactly one home.
"""
import array
import base64
import os
import struct
import threading
import time

from openai import OpenAI

from services.model_catalog import EMBEDDING_PROFILE, extract_usage
from services.openai_retry import call_with_retry, OpenAICallFailed

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover - scoring falls back to pure Python
    np = None
    NUMPY_AVAILABLE = False

# Chunks are ~800 tokens, so 96 of them is ~77k tokens - comfortably inside the
# request limit while keeping the number of round trips low.
_BATCH_TOKEN_BUDGET = 250000

_service = None
_service_lock = threading.Lock()


class EmbeddingService:
    def __init__(self, api_key=None, client=None):
        self.profile = EMBEDDING_PROFILE
        self.dimensions = EMBEDDING_PROFILE.dimensions
        self.api_key = api_key if api_key is not None else os.getenv('OPENAI_API_KEY')
        if client is not None:
            self.client = client
        elif self.api_key:
            # max_retries=0: services/openai_retry.py is the single retry
            # authority. Leaving the SDK's default 2 in place would multiply.
            self.client = OpenAI(api_key=self.api_key, max_retries=0, timeout=60.0)
        else:
            self.client = None
        self._query_cache = {}
        self._query_cache_lock = threading.Lock()

    def available(self):
        return self.client is not None

    # ---- embedding -----------------------------------------------------

    def _embed_batch(self, texts, *, timeout, attempts, base_delay, deadline,
                     logger, counter, op, log_fields=None):
        def call():
            return self.client.embeddings.create(
                model=self.profile.model_id,
                input=texts,
                dimensions=self.dimensions,
                timeout=timeout,
            )
        return call_with_retry(call, op=op, attempts=attempts, base_delay=base_delay,
                               deadline=deadline, logger=logger, counter=counter,
                               log_fields=log_fields or {})

    def embed_documents(self, texts, *, progress=None, usage_sink=None,
                        deadline=None, counter=None, logger=None):
        """Embed every chunk, in order. Returns a list of normalized vectors.

        Raises OpenAICallFailed if a batch cannot be completed. The caller turns
        that into a failed run - a partial index would silently answer some
        questions and not others, which is the class of bug this phase removes.
        """
        texts = list(texts or [])
        if not texts:
            return []
        if not self.available():
            raise OpenAICallFailed('embeddings: no API key configured',
                                   code='no_api_key', op='embeddings.batch',
                                   attempts=0, retryable=False)

        batches = self._plan_batches(texts)
        vectors = []
        for index, batch in enumerate(batches, start=1):
            started = time.monotonic()
            response = self._embed_batch(
                batch, timeout=60.0, attempts=4, base_delay=1.0, deadline=deadline,
                logger=logger, counter=counter, op='embeddings.batch',
                log_fields={'batch': index, 'batches': len(batches)})

            # The API returns data in input order, but it also returns an
            # explicit index. Sort by it rather than trusting the order.
            items = sorted(response.data, key=lambda item: getattr(item, 'index', 0))
            for item in items:
                vectors.append(self.normalize(item.embedding))

            usage = extract_usage(response)
            if usage and usage_sink is not None:
                usage_sink.append(usage)
            if logger:
                logger.event('training.embed.batch', batch=index, batches=len(batches),
                             texts=len(batch), tokens=(usage or {}).get('total_tokens', 0),
                             ms=int((time.monotonic() - started) * 1000))
            if progress:
                progress(index, len(batches))

        return vectors

    def _plan_batches(self, texts):
        """Split by count and by a token budget, so one huge chunk can't blow a batch."""
        from services.text_chunker import estimate_tokens
        batches, current, current_tokens = [], [], 0
        for text in texts:
            tokens = estimate_tokens(text)
            too_many = len(current) >= self.profile.max_batch
            too_big = current and (current_tokens + tokens) > _BATCH_TOKEN_BUDGET
            if too_many or too_big:
                batches.append(current)
                current, current_tokens = [], 0
            current.append(text)
            current_tokens += tokens
        if current:
            batches.append(current)
        return batches

    def embed_query(self, text, *, usage_sink=None, logger=None):
        """Embed one visitor question. Returns None on failure - never raises.

        A retrieval hiccup must not cost the visitor an answer: the caller falls
        back to keyword matching over kb_facts. That is a legitimate degradation,
        unlike the training bug this phase fixes - nothing here reports success
        for work that did not happen, and the fallback is logged.
        """
        if not text or not self.available():
            return None
        key = ' '.join(text.lower().split())
        if not key:
            return None

        with self._query_cache_lock:
            cached = self._query_cache.get(key)
        if cached is not None:
            return cached

        try:
            response = self._embed_batch(
                [key], timeout=8.0, attempts=2, base_delay=0.25,
                deadline=time.monotonic() + 6.0, logger=logger, counter=None,
                op='embeddings.query')
        except Exception as error:
            if logger:
                logger.event('chat.embed_query.failed', error_type=type(error).__name__)
            return None

        vector = self.normalize(response.data[0].embedding)
        usage = extract_usage(response)
        if usage and usage_sink is not None:
            usage_sink.append(usage)

        with self._query_cache_lock:
            # FAQ bots ask the same handful of questions constantly, so a small
            # cache pays for itself. Recorded usage then under-counts per-request,
            # which is correct: it matches what we actually spent.
            if len(self._query_cache) >= 512:
                self._query_cache.clear()
            self._query_cache[key] = vector
        return vector

    # ---- vector codec --------------------------------------------------

    @staticmethod
    def normalize(vector):
        """L2-normalize, so similarity scoring is a plain dot product."""
        values = [float(v) for v in vector]
        norm = sum(v * v for v in values) ** 0.5
        if norm <= 0:
            return values
        return [v / norm for v in values]

    @staticmethod
    def encode_b64(vectors):
        """float32 little-endian, base64 per vector.

        JSON float text runs ~9 bytes per float; packed float32 is 4, and base64
        brings that back to ~5.3 chars. At the 1500-chunk cap that is the
        difference between a 4 MB artifact and a 20 MB one.
        """
        encoded = []
        for vector in vectors:
            packed = struct.pack('<%df' % len(vector), *[float(v) for v in vector])
            encoded.append(base64.b64encode(packed).decode('ascii'))
        return encoded

    @staticmethod
    def decode_b64(b64_list, dimensions):
        """Decode to a numpy (n, d) float32 matrix, or a list of array('f') without numpy."""
        rows = []
        for blob in (b64_list or []):
            try:
                raw = base64.b64decode(blob)
                values = array.array('f')
                values.frombytes(raw)
            except Exception:
                continue  # a corrupt row must not cost the whole index
            if dimensions and len(values) != dimensions:
                continue
            rows.append(values)
        if not rows:
            return None
        if NUMPY_AVAILABLE:
            return np.array([list(row) for row in rows], dtype='float32')
        return rows

    @staticmethod
    def score(matrix, query_vector):
        """Cosine similarity for L2-normalized vectors == dot product."""
        if matrix is None or not query_vector:
            return []
        if NUMPY_AVAILABLE and hasattr(matrix, 'dot'):
            return matrix.dot(np.array(query_vector, dtype='float32')).tolist()
        return [sum(a * b for a, b in zip(row, query_vector)) for row in matrix]


def get_embedding_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmbeddingService()
    return _service
